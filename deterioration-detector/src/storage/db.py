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

READ-WRITE BY DEFAULT
---------------------
The API can add and delete admissions (see storage/mutations.py), so the local
file has to be opened writable. DuckDB refuses to open one file under two
different configurations in the same process — a read-only connection anywhere
makes every later read-write open fail with "Can't open a connection to same
database file with a different configuration". So every connection uses the
same read-write config; several may be open at once and they see each other's
committed writes.

The cost is DuckDB's single-writer file lock: while the API is running, another
process cannot open the same database (so `build_db.py` / `build_risk.py` need
the server stopped).
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


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the labs database. Leave `read_only` alone unless nothing else in
    the process will hold a connection — mixing configurations is an error."""
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
