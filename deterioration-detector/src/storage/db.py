"""
STORAGE LAYER
=============
Thin query helpers over the processed DuckDB file. Keeps SQL in one place so the
API and the risk-precompute script share the same access code.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "labs.duckdb"


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def admission_series(con, subject_id: int, hadm_id: int) -> dict:
    """
    Return {itemid: {"test_name","unit","points":[(charttime,value)...ordered]}}
    for one admission, oldest measurement first.
    """
    rows = con.execute("""
        SELECT itemid, test_name, unit, charttime, value
        FROM labs_clean
        WHERE subject_id = ? AND hadm_id = ?
        ORDER BY itemid, charttime
    """, [subject_id, hadm_id]).fetchall()

    out: dict = {}
    for itemid, test_name, unit, charttime, value in rows:
        d = out.setdefault(itemid, {"test_name": test_name, "unit": unit, "points": []})
        d["points"].append((charttime, value))
    return out
