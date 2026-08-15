"""
M3-M6 PRECOMPUTE
================
Runs the Python analysis engine (trend + anomaly + risk score) over EVERY
admission and stores a `risk_summary` table, so the dashboard's triage board
loads instantly for all ~57k admissions instead of scoring on the fly.

Heavy lifting (scanning 4.6M rows) is done in DuckDB; the lightweight scoring
logic runs in Python on the last few values per lab.

Run AFTER build_db.py:  python scripts/build_risk.py
"""
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.storage.db import connect  # noqa: E402
from src.analysis.risk_score import LabState, score_admission  # noqa: E402
from src.analysis.lead_time import compute_lead_time  # noqa: E402

WINDOW = 3  # how many recent values per lab the trend detector needs


def main() -> None:
    con = connect(read_only=False)
    t0 = time.time()

    print(f"[1/2] Pulling last {WINDOW} values per lab per admission ...")
    # keep only the most recent WINDOW measurements of each lab in each admission
    rows = con.execute(f"""
        SELECT subject_id, hadm_id, itemid, test_name, unit, value
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY subject_id, hadm_id, itemid
                ORDER BY charttime DESC
            ) AS rn
            FROM labs_clean
        )
        WHERE rn <= {WINDOW}
        ORDER BY subject_id, hadm_id, itemid, charttime
    """).fetchall()

    # group -> series per (admission, lab)
    series = defaultdict(lambda: defaultdict(list))   # (subj,hadm) -> itemid -> [values newest-window..]
    meta = {}                                         # itemid -> (test_name, unit)
    order = defaultdict(list)                          # preserve admission order
    seen = set()
    for subj, hadm, itemid, name, unit, value in rows:
        key = (subj, hadm)
        if key not in seen:
            seen.add(key)
            order["all"].append(key)
        series[key][itemid].append(value)
        meta[itemid] = (name, unit)

    print(f"[2/2] Scoring {len(series):,} admissions ...")
    con.execute("""CREATE OR REPLACE TABLE risk_summary(
        subject_id INTEGER, hadm_id INTEGER, score INTEGER, category VARCHAR,
        n_high INTEGER, n_worsening INTEGER
    )""")

    batch = []
    for (subj, hadm) in order["all"]:
        states = []
        for itemid, vals in series[(subj, hadm)].items():
            name, unit = meta[itemid]
            states.append(LabState(
                itemid=itemid, test_name=name, unit=unit,
                latest_value=vals[-1], series=vals,
            ))
        risk = score_admission(states)
        n_high = sum(1 for c in risk.contributions if c["status"] == "critical")
        n_wors = sum(1 for c in risk.contributions if c["trend"] == "worsening")
        batch.append((subj, hadm, risk.score, risk.category, n_high, n_wors))

    con.executemany("INSERT INTO risk_summary VALUES (?,?,?,?,?,?)", batch)
    con.execute("CREATE INDEX idx_risk ON risk_summary(category, score)")

    dist = con.execute("""
        SELECT category, COUNT(*) FROM risk_summary GROUP BY category
    """).fetchall()
    print(f"      Done in {time.time()-t0:.1f}s | risk distribution: {dict(dist)}")

    build_flag_eval(con)
    build_lead_time(con)
    con.close()


def build_flag_eval(con) -> None:
    """
    Score our reference-range detector against MIMIC's own `FLAG` column.

    Per clean value:  predicted positive = value outside our normal range
    (lab_def low/high, i.e. classify() != normal); actual positive = FLAG marked
    'abnormal'. We aggregate the 2x2 confusion-matrix counts per lab (and the API
    sums them for the overall view). All done in DuckDB -- no row-by-row Python.

    Admissions added through the dashboard are excluded: they carry no MIMIC
    FLAG, so counting them would silently score the detector against a ground
    truth that does not exist.
    """
    print("[+] Evaluating detector vs MIMIC FLAG (confusion matrix per lab) ...")
    # Databases built before provenance tracking have no `source` column.
    con.execute("ALTER TABLE labs_clean ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'mimic'")
    con.execute("""
        CREATE OR REPLACE TABLE flag_eval AS
        SELECT
            l.itemid,
            l.test_name,
            SUM(CASE WHEN pred AND act THEN 1 ELSE 0 END)         AS tp,
            SUM(CASE WHEN pred AND NOT act THEN 1 ELSE 0 END)     AS fp,
            SUM(CASE WHEN NOT pred AND act THEN 1 ELSE 0 END)     AS fn,
            SUM(CASE WHEN NOT pred AND NOT act THEN 1 ELSE 0 END) AS tn
        FROM (
            SELECT
                c.itemid,
                c.test_name,
                (c.value < d.low OR c.value > d.high) AS pred,
                (lower(coalesce(c.flag, '')) = 'abnormal') AS act
            FROM labs_clean c
            JOIN lab_def d ON d.itemid = c.itemid
            WHERE coalesce(c.source, 'mimic') = 'mimic'
        ) l
        GROUP BY l.itemid, l.test_name
    """)
    tot = con.execute(
        "SELECT SUM(tp), SUM(fp), SUM(fn), SUM(tn) FROM flag_eval").fetchone()
    print(f"      Overall  tp={tot[0]:,} fp={tot[1]:,} fn={tot[2]:,} tn={tot[3]:,}")


def build_lead_time(con) -> None:
    """
    Compute the early-warning lead time for EVERY admission and store it.

    For each admission we replay its labs chronologically and record when our
    risk score first hit High (the alert) versus when the first critical value
    appeared (the deterioration event); the gap is the lead time. The headline
    "flagged a median of N hours early" is then a one-line query over this table.

    The full per-admission timeline is streamed admission-by-admission (rows come
    back ordered), so memory stays flat even on the full 4.6M-row dataset.
    """
    print("[+] Computing early-warning lead time per admission ...")
    con.execute("""CREATE OR REPLACE TABLE lead_time(
        subject_id INTEGER, hadm_id INTEGER,
        deteriorated BOOLEAN, concerned BOOLEAN, alerted BOOLEAN,
        event_hours DOUBLE, concern_hours DOUBLE, alert_hours DOUBLE,
        lead_concern_hours DOUBLE, lead_alert_hours DOUBLE,
        event_lab VARCHAR
    )""")

    cur = con.execute("""
        SELECT subject_id, hadm_id, itemid, test_name, unit, charttime, value
        FROM labs_clean
        ORDER BY subject_id, hadm_id, charttime, itemid
    """)

    batch = []

    def flush(key, series):
        if not series:
            return
        r = compute_lead_time(series)
        batch.append((key[0], key[1], r.deteriorated, r.concerned, r.alerted,
                      r.event_hours, r.concern_hours, r.alert_hours,
                      r.lead_concern_hours, r.lead_alert_hours, r.event_lab))

    cur_key, series = None, {}
    while True:
        rows = cur.fetchmany(50_000)
        if not rows:
            break
        for subj, hadm, itemid, name, unit, t, v in rows:
            key = (subj, hadm)
            if key != cur_key:
                flush(cur_key, series)
                cur_key, series = key, {}
            d = series.setdefault(itemid, {"test_name": name, "unit": unit, "points": []})
            d["points"].append((t, v))
    flush(cur_key, series)

    con.executemany("INSERT INTO lead_time VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)

    n_det, n_early, med = con.execute("""
        SELECT
            SUM(CASE WHEN deteriorated THEN 1 ELSE 0 END),
            SUM(CASE WHEN deteriorated AND concerned AND lead_concern_hours > 0
                     THEN 1 ELSE 0 END),
            median(CASE WHEN deteriorated AND concerned AND lead_concern_hours > 0
                        THEN lead_concern_hours END)
        FROM lead_time
    """).fetchone()
    n_det = n_det or 0
    n_early = n_early or 0
    rate = (100 * n_early / n_det) if n_det else 0.0
    med = med or 0.0
    print(f"      {n_early:,}/{n_det:,} deteriorating admissions had an early "
          f"concern ({rate:.0f}%), median lead {med:.1f}h before first critical value")


if __name__ == "__main__":
    main()
