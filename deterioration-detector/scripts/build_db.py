"""
M1 INGESTION + M2 PREPROCESSING
===============================
Reads the full LABEVENTS.csv (~27.8M rows, 1.85 GB) WITHOUT loading it into RAM,
using DuckDB's streaming CSV reader. Filters to the 8 core labs, cleans the data,
maps ITEMID -> readable test names, and writes a compact analytical database
(data/processed/labs.duckdb) used by the rest of the system.

Run:  python scripts/build_db.py
"""
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.lab_dictionary import LAB_DEFS, CORE_ITEMIDS  # noqa: E402

RAW_CSV = ROOT / "data" / "raw" / "LABEVENTS.csv"
SAMPLE_CSV = ROOT / "data" / "sample" / "LABEVENTS_sample.csv"
OUT_DB = ROOT / "data" / "processed" / "labs.duckdb"


def resolve_csv() -> Path:
    """Use the full MIMIC dump if present, otherwise fall back to the bundled
    sample so a fresh clone runs end-to-end without the credentialed download."""
    if RAW_CSV.exists():
        print(f"[0/4] Using full dataset: {RAW_CSV}")
        return RAW_CSV
    if SAMPLE_CSV.exists():
        print(f"[0/4] Full dataset not found -> using bundled SAMPLE: {SAMPLE_CSV}")
        print("      (regenerate with scripts/generate_sample_data.py)")
        return SAMPLE_CSV
    sys.exit(f"No data found. Expected {RAW_CSV} or {SAMPLE_CSV}")


def main() -> None:
    csv_path = resolve_csv()

    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DB.exists():
        OUT_DB.unlink()

    con = duckdb.connect(str(OUT_DB))
    t0 = time.time()

    # --- reference table built from the Python lab dictionary (single source of truth) ---
    con.execute("""
        CREATE TABLE lab_def(
            itemid INTEGER, name VARCHAR, unit VARCHAR,
            low DOUBLE, high DOUBLE, pmin DOUBLE, pmax DOUBLE, worsening VARCHAR
        )""")
    con.executemany(
        "INSERT INTO lab_def VALUES (?,?,?,?,?,?,?,?)",
        [(d.itemid, d.name, d.unit, d.low, d.high, d.plausible_min, d.plausible_max, d.worsening)
         for d in LAB_DEFS.values()],
    )

    idlist = ",".join(str(i) for i in CORE_ITEMIDS)
    print(f"[1/4] Streaming + filtering rows to {len(CORE_ITEMIDS)} core labs ...")

    # M1 read raw (streamed) + M2 clean, all pushed down into DuckDB:
    #   - keep only core labs
    #   - drop rows without a numeric value (text-only results)
    #   - clip physiologically implausible / sentinel values (e.g. the -1 placeholders)
    con.execute(f"""
        CREATE TABLE labs_clean AS
        SELECT
            r.SUBJECT_ID::INTEGER          AS subject_id,
            r.HADM_ID::INTEGER             AS hadm_id,
            r.ITEMID::INTEGER              AS itemid,
            d.name                         AS test_name,
            CAST(r.CHARTTIME AS TIMESTAMP) AS charttime,
            r.VALUENUM::DOUBLE             AS value,
            d.unit                         AS unit,
            r.FLAG                         AS flag
        FROM read_csv_auto('{csv_path.as_posix()}', header=true) r
        JOIN lab_def d ON d.itemid = r.ITEMID::INTEGER
        WHERE r.ITEMID IN ({idlist})
          AND r.VALUENUM IS NOT NULL
          AND r.HADM_ID IS NOT NULL
          AND r.VALUENUM::DOUBLE BETWEEN d.pmin AND d.pmax
          AND r.CHARTTIME IS NOT NULL
    """)

    # dedupe identical measurements
    con.execute("""
        CREATE TABLE labs_dedup AS
        SELECT DISTINCT subject_id, hadm_id, itemid, test_name, charttime, value, unit, flag
        FROM labs_clean
    """)
    con.execute("DROP TABLE labs_clean")
    con.execute("ALTER TABLE labs_dedup RENAME TO labs_clean")
    con.execute("CREATE INDEX idx_sh ON labs_clean(subject_id, hadm_id)")

    print("[2/4] Building admissions index ...")
    # one row per hospital admission: how much data, time span (relative hours)
    con.execute("""
        CREATE TABLE admissions AS
        SELECT
            subject_id,
            hadm_id,
            COUNT(*)                                   AS n_measurements,
            COUNT(DISTINCT itemid)                     AS n_labs,
            MIN(charttime)                             AS first_time,
            MAX(charttime)                             AS last_time,
            date_diff('hour', MIN(charttime), MAX(charttime)) AS span_hours
        FROM labs_clean
        GROUP BY subject_id, hadm_id
    """)

    # --- report ---
    raw_rows = con.execute(
        f"SELECT COUNT(*) FROM read_csv_auto('{csv_path.as_posix()}', header=true)"
    ).fetchone()[0]
    kept = con.execute("SELECT COUNT(*) FROM labs_clean").fetchone()[0]
    n_pat = con.execute("SELECT COUNT(DISTINCT subject_id) FROM labs_clean").fetchone()[0]
    n_adm = con.execute("SELECT COUNT(*) FROM admissions").fetchone()[0]
    elapsed = time.time() - t0

    # persist a tiny stats table the dashboard shows as the "scale story"
    con.execute("CREATE TABLE pipeline_stats(metric VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO pipeline_stats VALUES (?,?)", [
        ("raw_rows", str(raw_rows)),
        ("kept_rows", str(kept)),
        ("patients", str(n_pat)),
        ("admissions", str(n_adm)),
        ("core_labs", str(len(CORE_ITEMIDS))),
        ("build_seconds", f"{elapsed:.1f}"),
    ])

    print(f"[3/4] Done in {elapsed:.1f}s")
    print(f"[4/4] raw={raw_rows:,} -> kept={kept:,} | patients={n_pat:,} | admissions={n_adm:,}")
    print(f"      Output: {OUT_DB}")
    con.close()


if __name__ == "__main__":
    main()
