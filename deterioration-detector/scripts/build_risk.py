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
        ORDER BY subject_id, hadm_id, itemid, value
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
    con.close()


if __name__ == "__main__":
    main()
