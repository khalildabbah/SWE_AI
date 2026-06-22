"""
STORAGE LAYER
=============
Thin query helpers over the processed labs DB. Keeps SQL in one place so the
API and the risk-precompute script share the same access code.

Connection target:
  - If MOTHERDUCK_TOKEN is set, connect to the hosted MotherDuck database
    (cloud DuckDB) so every clone shares the full dataset.
  - Otherwise fall back to the local data/processed/labs.duckdb file.
The schema is identical either way, so all queries below are unchanged.
"""
import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "processed" / "labs.duckdb"

# Load MOTHERDUCK_TOKEN (and friends) from a local, gitignored .env if present.
load_dotenv(ROOT / ".env")

MD_DATABASE = os.getenv("MOTHERDUCK_DATABASE", "labs")


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        # The MotherDuck extension reads the token from this env var.
        os.environ.setdefault("motherduck_token", token)
        return duckdb.connect(f"md:{MD_DATABASE}")
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
