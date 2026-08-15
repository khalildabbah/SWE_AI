"""
ADMISSION WRITES
================
Adding and deleting an admission from the analytical database.

`labs_clean` is the only table anyone measures anything from; every other table
the dashboard reads is *derived* from it by scripts/build_db.py and
scripts/build_risk.py:

    labs_clean  ──┬─→ admissions     (row counts, time span)
                  ├─→ risk_summary   (score, category, counts)   [build_risk]
                  └─→ lead_time      (early-warning timings)     [build_risk]

A write that touched only `labs_clean` would leave the triage board, the score
and the Early Warning page disagreeing with the labs. So each mutation here
rewrites that admission's row in all four tables inside one transaction, using
the same scoring functions the precompute scripts use — never a reimplementation
of the maths.

NOT rebuilt here:
  * `flag_eval` (Detector Accuracy) is a comparison against MIMIC's own FLAG
    column. User-entered labs have no MIMIC flag, so they are excluded from that
    evaluation entirely — see the `source` column below.
  * `pipeline_stats.raw_rows` counts rows read from the source CSV, which a
    user-added admission does not change.
"""
from __future__ import annotations

import threading
from datetime import datetime

from src.analysis.lead_time import compute_lead_time
from src.analysis.risk_score import LabState, score_admission
from src.ingestion.lab_dictionary import LAB_DEFS
from src.storage.db import connect

# DuckDB handles concurrent connections, but "read the labs, recompute, write
# back" is read-modify-write: two adds racing on the same admission could both
# read an empty state. Writes are rare and cheap, so serialise them outright.
_WRITE_LOCK = threading.Lock()

MAX_MEASUREMENTS = 500  # a hand-entered admission; well past any real use


class ValidationError(ValueError):
    """Bad input from the client — surfaced as a 400, not a 500."""


def _ensure_source_column(con) -> None:
    """Mark where a lab row came from.

    Databases built before this feature have no `source` column; everything in
    them came from the MIMIC extract, which is exactly the default. Adding it is
    idempotent, so this is safe to call on every write.

    It matters because `flag_eval` scores our detector against MIMIC's own FLAG.
    User-entered rows have no such ground truth, and folding them in would
    quietly move the numbers on the Detector Accuracy page.
    """
    con.execute("ALTER TABLE labs_clean ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'mimic'")


def _validate(subject_id: int, hadm_id: int, measurements: list[dict]) -> list[tuple]:
    """Check the payload against the same rules the ingestion pipeline applies,
    and return rows ready for insertion."""
    if subject_id <= 0 or hadm_id <= 0:
        raise ValidationError("Patient ID and admission ID must be positive numbers.")
    if not measurements:
        raise ValidationError("At least one lab measurement is required.")
    if len(measurements) > MAX_MEASUREMENTS:
        raise ValidationError(f"Too many measurements (limit {MAX_MEASUREMENTS}).")

    rows, seen = [], set()
    for i, m in enumerate(measurements, start=1):
        itemid = m.get("itemid")
        d = LAB_DEFS.get(itemid)
        if d is None:
            raise ValidationError(f"Measurement {i}: unknown lab id {itemid!r}.")

        value = m.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValidationError(f"Measurement {i} ({d.name}): value must be a number.")
        # Same bound the pipeline uses to discard sentinel/garbage values, so a
        # hand-entered admission can't contain something build_db would drop.
        if not (d.plausible_min <= value <= d.plausible_max):
            raise ValidationError(
                f"Measurement {i} ({d.name}): {value} {d.unit} is outside the plausible "
                f"range {d.plausible_min}–{d.plausible_max} {d.unit}.")

        charttime = m.get("charttime")
        if isinstance(charttime, str):
            try:
                charttime = datetime.fromisoformat(charttime)
            except ValueError:
                raise ValidationError(f"Measurement {i} ({d.name}): invalid date/time.")
        if not isinstance(charttime, datetime):
            raise ValidationError(f"Measurement {i} ({d.name}): a date/time is required.")

        key = (itemid, charttime)
        if key in seen:
            raise ValidationError(
                f"Measurement {i} ({d.name}): duplicate reading at {charttime:%Y-%m-%d %H:%M}.")
        seen.add(key)

        rows.append((subject_id, hadm_id, itemid, d.name, charttime, value, d.unit, None, "user"))

    rows.sort(key=lambda r: (r[2], r[4]))  # itemid, charttime — matches read order
    return rows


def _series_from_rows(rows: list[tuple]) -> dict:
    """Rows → the {itemid: {test_name, unit, points}} shape the analysis layer
    takes, identical to storage.db.admission_series."""
    series: dict = {}
    for _, _, itemid, name, charttime, value, unit, _, _ in rows:
        d = series.setdefault(itemid, {"test_name": name, "unit": unit, "points": []})
        d["points"].append((charttime, value))
    for d in series.values():
        d["points"].sort(key=lambda p: p[0])
    return series


def _score_admission_rows(series: dict) -> tuple:
    """Score one admission's series with the shared engine. Returns
    (risk, n_high, n_worsening)."""
    WINDOW = 3  # recent values per lab the trend detector needs (matches build_risk.py)
    states = []
    for itemid, info in series.items():
        values = [v for (_, v) in info["points"]][-WINDOW:]
        states.append(LabState(
            itemid=itemid, test_name=info["test_name"], unit=info["unit"],
            latest_value=values[-1], series=values,
        ))
    risk = score_admission(states)
    n_high = sum(1 for c in risk.contributions if c["status"] == "critical")
    n_wors = sum(1 for c in risk.contributions if c["trend"] == "worsening")
    return risk, n_high, n_wors


def _refresh_stats(con) -> None:
    """Recompute the counters in the dashboard footer from the tables themselves,
    rather than trying to increment them (which drifts)."""
    kept = con.execute("SELECT COUNT(*) FROM labs_clean").fetchone()[0]
    patients = con.execute("SELECT COUNT(DISTINCT subject_id) FROM labs_clean").fetchone()[0]
    admissions = con.execute("SELECT COUNT(*) FROM admissions").fetchone()[0]
    for metric, value in (("kept_rows", kept), ("patients", patients),
                          ("admissions", admissions)):
        con.execute("UPDATE pipeline_stats SET value = ? WHERE metric = ?",
                    [str(value), metric])


def exists(subject_id: int, hadm_id: int) -> bool:
    con = connect()
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM labs_clean WHERE subject_id = ? AND hadm_id = ?",
            [subject_id, hadm_id]).fetchone()[0]
    finally:
        con.close()
    return n > 0


def create_admission(subject_id: int, hadm_id: int, measurements: list[dict]) -> dict:
    """Add a hand-entered admission and bring every derived table up to date."""
    rows = _validate(subject_id, hadm_id, measurements)

    with _WRITE_LOCK:
        con = connect()
        try:
            _ensure_source_column(con)
            clash = con.execute(
                "SELECT COUNT(*) FROM labs_clean WHERE subject_id = ? AND hadm_id = ?",
                [subject_id, hadm_id]).fetchone()[0]
            if clash:
                raise ValidationError(
                    f"Admission {hadm_id} already exists for patient {subject_id}.")

            con.execute("BEGIN TRANSACTION")
            try:
                con.executemany(
                    "INSERT INTO labs_clean "
                    "(subject_id, hadm_id, itemid, test_name, charttime, value, unit, flag, source)"
                    " VALUES (?,?,?,?,?,?,?,?,?)", rows)
                summary = _write_derived(con, subject_id, hadm_id)
                _refresh_stats(con)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    return {"subject_id": subject_id, "hadm_id": hadm_id,
            "n_measurements": len(rows), **summary}


def delete_admission(subject_id: int, hadm_id: int) -> dict:
    """Permanently remove an admission and everything derived from it."""
    with _WRITE_LOCK:
        con = connect()
        try:
            row = con.execute("""
                SELECT COUNT(*), COUNT(DISTINCT itemid)
                FROM labs_clean WHERE subject_id = ? AND hadm_id = ?
            """, [subject_id, hadm_id]).fetchone()
            n_measurements, n_labs = row[0], row[1]
            if not n_measurements:
                return {}

            con.execute("BEGIN TRANSACTION")
            try:
                for table in ("labs_clean", "admissions", "risk_summary", "lead_time"):
                    con.execute(
                        f"DELETE FROM {table} WHERE subject_id = ? AND hadm_id = ?",
                        [subject_id, hadm_id])
                _refresh_stats(con)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    # The per-pattern board rankings are a cache in a separate file; leaving the
    # row there would keep a deleted patient listed whenever a pattern is active.
    _forget_in_pattern_cache(subject_id, hadm_id)

    return {"subject_id": subject_id, "hadm_id": hadm_id,
            "n_measurements": n_measurements, "n_labs": n_labs}


def _write_derived(con, subject_id: int, hadm_id: int) -> dict:
    """Rebuild admissions / risk_summary / lead_time for one admission."""
    rows = con.execute("""
        SELECT itemid, test_name, unit, charttime, value
        FROM labs_clean
        WHERE subject_id = ? AND hadm_id = ?
        ORDER BY itemid, charttime
    """, [subject_id, hadm_id]).fetchall()

    series: dict = {}
    for itemid, name, unit, charttime, value in rows:
        d = series.setdefault(itemid, {"test_name": name, "unit": unit, "points": []})
        d["points"].append((charttime, value))

    for table in ("admissions", "risk_summary", "lead_time"):
        con.execute(f"DELETE FROM {table} WHERE subject_id = ? AND hadm_id = ?",
                    [subject_id, hadm_id])
    if not series:
        return {}

    con.execute("""
        INSERT INTO admissions
        SELECT subject_id, hadm_id, COUNT(*), COUNT(DISTINCT itemid),
               MIN(charttime), MAX(charttime),
               date_diff('hour', MIN(charttime), MAX(charttime))
        FROM labs_clean WHERE subject_id = ? AND hadm_id = ?
        GROUP BY subject_id, hadm_id
    """, [subject_id, hadm_id])

    risk, n_high, n_wors = _score_admission_rows(series)
    con.execute("INSERT INTO risk_summary VALUES (?,?,?,?,?,?)",
                [subject_id, hadm_id, risk.score, risk.category, n_high, n_wors])

    lt = compute_lead_time(series)
    con.execute("INSERT INTO lead_time VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        subject_id, hadm_id, lt.deteriorated, lt.concerned, lt.alerted,
        lt.event_hours, lt.concern_hours, lt.alert_hours,
        lt.lead_concern_hours, lt.lead_alert_hours, lt.event_lab,
    ])

    span = con.execute(
        "SELECT span_hours FROM admissions WHERE subject_id = ? AND hadm_id = ?",
        [subject_id, hadm_id]).fetchone()
    return {"score": risk.score, "category": risk.category,
            "n_high": n_high, "n_worsening": n_wors,
            "n_labs": len(series), "span_hours": span[0] if span else 0}


def _forget_in_pattern_cache(subject_id: int, hadm_id: int) -> None:
    """Best-effort removal from the pattern-ranking cache.

    Derived data: if the cache is missing or busy, the worst case is one stale
    row until the next rebuild, which must not fail the delete the user asked
    for."""
    try:
        from src.storage import pattern_risk
        pattern_risk.forget_admission(subject_id, hadm_id)
    except Exception:  # pragma: no cover - cache is advisory
        pass
