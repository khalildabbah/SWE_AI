"""
PATTERN STORE
=============
Where the Pattern Builder's user-authored syndromes actually live. One tiny
interface — `read_all()` / `write_all()` — over two interchangeable backends:

  * MotherDuck (cloud) — used whenever MOTHERDUCK_TOKEN is set, which is how the
    hosted deployment reads its data. A `custom_patterns` table in the cloud
    database survives container restarts and redeploys, so a pattern someone
    builds on the live site is still there tomorrow.
  * A local JSON file — the default for local development. Simple, inspectable,
    and needs no cloud account.

The two backends store the same thing: a {key: record} mapping, one record per
saved pattern. Only the transport differs, so `custom_syndromes` can do all its
validation and CRUD without caring which one is active.

Note for the data pipeline: `scripts/upload_to_motherduck.py` mirrors the local
DuckDB into the cloud. `custom_patterns` is never created in the local file, but
it is explicitly excluded there anyway so user-authored patterns can never be
overwritten by a dataset refresh.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data" / "custom_syndromes.json"

TABLE = "custom_patterns"


def use_cloud() -> bool:
    """True when patterns should be read/written in MotherDuck.

    Read at call time (not import time) so tests and scripts can toggle the
    backend by setting or clearing the environment variable.
    """
    return bool(os.getenv("MOTHERDUCK_TOKEN"))


# ── JSON file backend ────────────────────────────────────────────────────────

def _json_read() -> dict:
    if not STORE.exists():
        return {}
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _json_write(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── MotherDuck backend ───────────────────────────────────────────────────────

def _cloud_connect():
    """A writable connection to the cloud database.

    `db.connect()` returns a MotherDuck connection (writable) when the token is
    set; its read_only flag only ever applies to the local file.
    """
    from src.storage.db import connect
    return connect()


def _ensure_table(con) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            key      VARCHAR PRIMARY KEY,
            payload  VARCHAR,
            updated  VARCHAR
        )
    """)


def _cloud_read() -> dict:
    con = _cloud_connect()
    try:
        _ensure_table(con)
        rows = con.execute(f"SELECT key, payload FROM {TABLE}").fetchall()
    finally:
        con.close()

    out = {}
    for key, payload in rows:
        try:
            record = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue  # a corrupt row shouldn't take down the whole list
        if isinstance(record, dict):
            out[key] = record
    return out


def _cloud_write(data: dict) -> None:
    """Replace the stored set with `data`.

    `write_all` is always called with the complete mapping, so a delete shows up
    as an absent key — hence the wholesale replace rather than an upsert.
    """
    con = _cloud_connect()
    try:
        _ensure_table(con)
        con.execute(f"DELETE FROM {TABLE}")
        for key, record in data.items():
            con.execute(
                f"INSERT INTO {TABLE} (key, payload, updated) VALUES (?, ?, ?)",
                [key, json.dumps(record, ensure_ascii=False),
                 str(record.get("updated") or "")],
            )
    finally:
        con.close()


# ── Public interface ─────────────────────────────────────────────────────────

def read_all() -> dict:
    """Every saved pattern, as {key: record}. Never raises — a store that can't
    be reached reads as empty so the Pattern Builder still opens."""
    try:
        return _cloud_read() if use_cloud() else _json_read()
    except Exception:
        return {}


def write_all(data: dict) -> None:
    """Persist the complete {key: record} mapping."""
    if use_cloud():
        _cloud_write(data)
    else:
        _json_write(data)


def backend_name() -> str:
    """Which backend is active — surfaced in the UI so a user knows whether
    their patterns are stored durably or only for this container's lifetime."""
    return "motherduck" if use_cloud() else "file"
