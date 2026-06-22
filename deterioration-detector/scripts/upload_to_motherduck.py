"""
UPLOAD PROCESSED DB -> MOTHERDUCK
=================================
One-time (re-runnable) push of the local processed database
(data/processed/labs.duckdb) into a hosted MotherDuck database so every clone
shares the full dataset instead of the bundled 86 MB sample.

Setup:
    1. Grab your token from the MotherDuck UI (Settings -> Access Tokens).
    2. export MOTHERDUCK_TOKEN="<your token>"
    3. python scripts/upload_to_motherduck.py

Safe to re-run: each table is replaced (CREATE OR REPLACE) from the local copy.
"""
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "processed" / "labs.duckdb"
MD_DATABASE = os.getenv("MOTHERDUCK_DATABASE", "labs")


def main() -> None:
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        sys.exit("MOTHERDUCK_TOKEN is not set. export it first (see this file's header).")
    if not DB_PATH.exists():
        sys.exit(f"Local processed DB not found: {DB_PATH}\nRun scripts/build_db.py first.")

    os.environ.setdefault("motherduck_token", token)

    # Connect to MotherDuck (default catalog), then attach the local file read-only.
    con = duckdb.connect("md:")
    con.execute(f"ATTACH '{DB_PATH.as_posix()}' AS local_db (READ_ONLY)")
    con.execute(f"CREATE DATABASE IF NOT EXISTS {MD_DATABASE}")

    tables = [
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = 'local_db' AND table_schema = 'main'"
        ).fetchall()
    ]
    if not tables:
        sys.exit("No tables found in the local database.")

    print(f"Uploading {len(tables)} table(s) to MotherDuck database '{MD_DATABASE}':")
    for t in tables:
        con.execute(
            f'CREATE OR REPLACE TABLE {MD_DATABASE}.main."{t}" AS '
            f'SELECT * FROM local_db.main."{t}"'
        )
        n = con.execute(f'SELECT COUNT(*) FROM {MD_DATABASE}.main."{t}"').fetchone()[0]
        print(f"  - {t:<16} {n:>12,} rows")

    con.close()
    print(f"\nDone. The app will use the cloud DB whenever MOTHERDUCK_TOKEN is set.")


if __name__ == "__main__":
    main()
