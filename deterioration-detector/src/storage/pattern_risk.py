"""
PER-PATTERN COHORT RANKING
==========================
The triage board ranks admissions by risk. With a user-built pattern active it
must rank by *that pattern's* score instead of the built-in one — "show me the
patients who most look like this syndrome".

Scoring the whole cohort live is not an option: the trend bonus needs each lab's
recent series, not just its latest value, which is exactly why the built-in
score is precomputed into `risk_summary` by scripts/build_risk.py. So we do the
same thing per pattern: `build()` scores every admission once and caches the
result, and the board just reads it back, filtered and paginated in SQL.

WHERE THE CACHE LIVES
---------------------
Alongside the labs database when that is MotherDuck (writable, so the board can
join it directly), and in a SEPARATE local DuckDB file otherwise — the local
labs file is opened read-only and DuckDB will not hand out a write lock on a
file that read-only connections are already using.

The cache is derived data: deleting it costs a rebuild, never any user content.
It is rebuilt whenever the pattern that produced it is saved or imported.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from pathlib import Path

import duckdb

from src.analysis.pattern_engine import CRITERIA_VERSION, LabState, evaluate_pattern
from src.storage.db import connect
from src.storage import pattern_store

ROOT = Path(__file__).resolve().parents[2]
CACHE_DB = ROOT / "data" / "processed" / "pattern_risk.duckdb"

TABLE = "pattern_risk"
WINDOW = 3  # recent values per lab the trend detector needs (matches build_risk)

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    pattern_key VARCHAR,
    subject_id  INTEGER,
    hadm_id     INTEGER,
    score       INTEGER,
    category    VARCHAR,
    n_matched   INTEGER,
    n_high      INTEGER,
    n_worsening INTEGER,
    -- what counted as a match when these rows were written; rows from an older
    -- definition are ignored rather than silently served
    criteria    INTEGER DEFAULT 0
)
"""


# Saving a pattern schedules a rebuild in the background, and the user can also
# trigger one directly. Those two run on separate connections, and each one's
# "delete then insert" cannot see the other's uncommitted rows — so both commit
# and every admission lands in the cache twice. Serialising per pattern is the
# honest fix: rebuilds are seconds apart at worst and never need to overlap.
_BUILD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _build_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _BUILD_LOCKS.setdefault(key, threading.Lock())


def _cache_connect():
    """A writable connection to wherever the cache lives."""
    if pattern_store.use_cloud():
        return connect()                      # MotherDuck: same catalog, writable
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(CACHE_DB))      # local: its own file, its own lock


def attach(con) -> str:
    """Make the cache readable on a labs connection; return the table reference.

    On MotherDuck the cache is already in the same catalog. Locally it is a
    separate file, so attach it read-only — that keeps the board's query a plain
    SQL join instead of stitching two result sets together in Python.
    """
    if pattern_store.use_cloud():
        con.execute(DDL)
        return f"(SELECT * FROM {TABLE} WHERE criteria = {CRITERIA_VERSION})"
    if not CACHE_DB.exists():
        return ""                             # nothing built yet
    con.execute(f"ATTACH IF NOT EXISTS '{CACHE_DB.as_posix()}' AS pr (READ_ONLY)")
    return (f"(SELECT * FROM pr.main.{TABLE} "
            f"WHERE criteria = {CRITERIA_VERSION})")


def is_built(pattern_key: str) -> bool:
    """Has this pattern's ranking been computed by the CURRENT match definition?

    Rows written before the definition changed are not a valid cache — treating
    them as absent forces a rebuild instead of serving a ranking that disagrees
    with the pattern.
    """
    if not pattern_store.use_cloud() and not CACHE_DB.exists():
        return False
    con = _cache_connect()
    try:
        con.execute(DDL)
        n = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE pattern_key = ? AND criteria = ?",
            [pattern_key, CRITERIA_VERSION]).fetchone()[0]
    finally:
        con.close()
    return n > 0


def clear(pattern_key: str) -> None:
    """Drop a pattern's cached ranking (it is stale, or the pattern is gone)."""
    if not pattern_store.use_cloud() and not CACHE_DB.exists():
        return
    con = _cache_connect()
    try:
        con.execute(DDL)
        con.execute(f"DELETE FROM {TABLE} WHERE pattern_key = ?", [pattern_key])
    finally:
        con.close()


def forget_admission(subject_id: int, hadm_id: int) -> None:
    """Drop one admission from every pattern's cached ranking.

    Called when an admission is deleted: the cache is keyed by admission, so
    without this the board would keep listing a patient that no longer exists
    for as long as a pattern is the active scoring selection — until something
    forced a rebuild.
    """
    if not pattern_store.use_cloud() and not CACHE_DB.exists():
        return
    con = _cache_connect()
    try:
        con.execute(DDL)
        con.execute(f"DELETE FROM {TABLE} WHERE subject_id = ? AND hadm_id = ?",
                    [subject_id, hadm_id])
    finally:
        con.close()


def build(pattern: dict) -> int:
    """Score every admission against one pattern and cache the ranking.

    Returns how many admissions were scored. A pattern with no testable rule
    caches nothing — there would be nothing to rank by. Concurrent rebuilds of
    the same pattern are serialised; the last one wins.
    """
    key = pattern.get("key") or ""
    signals = [s for s in (pattern.get("signals") or [])
               if s.get("in_dataset") and s.get("itemid") is not None]
    if not key or not signals:
        return 0
    with _build_lock(key):
        return _build_locked(key, pattern, signals)


def _build_locked(key: str, pattern: dict, signals: list[dict]) -> int:
    itemids = sorted({s["itemid"] for s in signals})
    placeholders = ", ".join("?" for _ in itemids)

    # Only the pattern's own labs, and only their last WINDOW values — far less
    # data than the built-in precompute, which needs all eight.
    labs = connect()
    try:
        rows = labs.execute(f"""
            SELECT subject_id, hadm_id, itemid, test_name, unit, value
            FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY subject_id, hadm_id, itemid
                    ORDER BY charttime DESC
                ) AS rn
                FROM labs_clean
                WHERE itemid IN ({placeholders})
            )
            WHERE rn <= {WINDOW}
            ORDER BY subject_id, hadm_id, itemid, charttime
        """, itemids).fetchall()
    finally:
        labs.close()

    series: dict = defaultdict(lambda: defaultdict(list))
    meta: dict = {}
    order, seen = [], set()
    for subj, hadm, itemid, name, unit, value in rows:
        adm = (subj, hadm)
        if adm not in seen:
            seen.add(adm)
            order.append(adm)
        series[adm][itemid].append(value)
        meta[itemid] = (name, unit)

    batch = []
    for adm in order:
        states = [
            LabState(itemid=iid, test_name=meta[iid][0], unit=meta[iid][1],
                     latest_value=vals[-1], series=vals)
            for iid, vals in series[adm].items()
        ]
        # Rank exactly the admissions the pattern says it matches. Scoring
        # "anything with some evidence" would list patients here who show no
        # pattern card when opened and are absent from the pattern's own cohort
        # run — the board would be claiming a match the pattern never made.
        result = evaluate_pattern(states, signals, pattern.get("min_signals"))
        if not result.matched:
            continue
        n_high = sum(1 for r in result.fired_rules if r.status == "critical")
        n_wors = sum(1 for r in result.fired_rules if r.trend == "worsening")
        batch.append((key, adm[0], adm[1], result.score, result.category,
                      result.n_fired, n_high, n_wors, CRITERIA_VERSION))

    cache = _cache_connect()
    try:
        cache.execute(DDL)
        # Replace in one transaction. A save schedules a rebuild in the
        # background and the user can also trigger one explicitly; without this
        # the two interleave as delete/delete/insert/insert and the pattern ends
        # up with every admission cached twice.
        cache.execute("BEGIN TRANSACTION")
        try:
            cache.execute(f"DELETE FROM {TABLE} WHERE pattern_key = ?", [key])
            if batch:
                cache.executemany(
                    f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?,?,?)", batch)
            cache.execute("COMMIT")
        except Exception:
            cache.execute("ROLLBACK")
            raise
    finally:
        cache.close()
    return len(batch)


def ensure_built(pattern: dict) -> None:
    """Build the ranking if it is missing, so the board is never empty just
    because nobody rebuilt it."""
    key = pattern.get("key") or ""
    if key and not is_built(key):
        build(pattern)
