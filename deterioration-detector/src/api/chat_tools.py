"""
CHATBOT DATA TOOLS
==================
Read-only "tools" the Gemini agent is allowed to call to answer questions about
THIS dataset (and nothing else). Every function returns plain JSON-serialisable
dicts so they can be handed straight back to the model.

Design choices:
  * The agent never writes SQL or touches the DB directly. It can only call the
    small, audited set of functions in `build_toolset()`, each of which opens a
    read-only connection. This is the safety boundary for the "only answer about
    the dataset" requirement.
  * Charts are produced as a side effect: when the agent fetches a lab series for
    display it appends a chart spec to a request-scoped collector, which the API
    returns alongside the text so the React widget can render it inline.

Time windows ("last 7 days") are anchored to each PATIENT'S OWN latest
measurement, because MIMIC-III timestamps are de-identified and shifted into the
future per patient — wall-clock "now" matches almost no rows. The anchoring lives
in `_window_clause()` so it is easy to revisit later.
"""
from __future__ import annotations

from src.storage.db import connect, admission_series
from src.analysis.risk_score import LabState, score_admission
from src.analysis.alerts import build_alerts
from src.analysis.trajectory import compute_trajectory
from src.analysis.syndromes import detect_syndromes
from src.ingestion.lab_dictionary import LAB_DEFS

# Lab name -> itemid lookup that tolerates aliases/casing so the model can pass
# "BUN", "wbc", "blood sugar", etc. without us having to teach it exact strings.
_ALIASES = {
    "bun": 51006, "urea": 51006, "urea nitrogen": 51006,
    "wbc": 51301, "white blood cells": 51301, "white blood cell": 51301,
    "white cells": 51301, "leukocytes": 51301,
    "creatinine": 50912, "cr": 50912,
    "potassium": 50971, "k": 50971,
    "sodium": 50983, "na": 50983,
    "bicarbonate": 50882, "bicarb": 50882, "hco3": 50882, "co2": 50882,
    "hematocrit": 51221, "hct": 51221,
    "lactate": 50813, "lactic acid": 50813,
}


def _resolve_lab(lab_name: str) -> int | None:
    """Map a free-text lab name to an itemid, or None if not one of our 8 labs."""
    key = (lab_name or "").strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    for itemid, d in LAB_DEFS.items():
        if d.name.lower() == key:
            return itemid
    return None


def _window_clause(con, subject_id: int, hadm_id: int, last_n_days: int | None):
    """
    Build a SQL fragment + params restricting to the most recent `last_n_days`
    of an admission, anchored to that admission's latest measurement (not the
    real calendar clock — MIMIC dates are shifted). Returns ("", []) when no
    window is requested.
    """
    if not last_n_days or last_n_days <= 0:
        return "", []
    anchor = con.execute(
        "SELECT MAX(charttime) FROM labs_clean WHERE subject_id = ? AND hadm_id = ?",
        [subject_id, hadm_id],
    ).fetchone()[0]
    if anchor is None:
        return "", []
    return " AND charttime >= ? - INTERVAL (?) DAY", [anchor, int(last_n_days)]


def _states_for(series: dict) -> list[LabState]:
    states = []
    for itemid, info in series.items():
        values = [v for (_, v) in info["points"]]
        if not values:
            continue
        states.append(LabState(
            itemid=itemid, test_name=info["test_name"], unit=info["unit"],
            latest_value=values[-1], series=values,
        ))
    return states


# ── Tool implementations ──────────────────────────────────────────────────
# Each takes a connection (bound via closure in build_toolset) so the agent
# only ever sees the data-shaped arguments.

def _list_available_labs() -> dict:
    """Static description of the only labs this system tracks."""
    return {
        "labs": [
            {"test_name": d.name, "unit": d.unit,
             "normal_low": d.low, "normal_high": d.high}
            for d in LAB_DEFS.values()
        ],
        "note": ("These 8 labs are the ONLY measurements in this dataset. "
                 "Anything else (e.g. blood sugar/glucose, blood pressure, "
                 "temperature) is NOT tracked and cannot be answered."),
    }


def _find_patient(con, subject_id: int) -> dict:
    rows = con.execute("""
        SELECT a.hadm_id, a.n_measurements, a.span_hours,
               r.score, r.category, r.n_high, r.n_worsening
        FROM admissions a
        LEFT JOIN risk_summary r USING (subject_id, hadm_id)
        WHERE a.subject_id = ?
        ORDER BY r.score DESC NULLS LAST
    """, [subject_id]).fetchall()
    if not rows:
        return {"found": False, "subject_id": subject_id,
                "message": f"No patient {subject_id} in the dataset."}
    cols = ["hadm_id", "n_measurements", "span_hours",
            "risk_score", "risk_category", "n_critical_labs", "n_worsening_labs"]
    return {"found": True, "subject_id": subject_id,
            "admissions": [dict(zip(cols, r)) for r in rows]}


def _get_admission_detail(con, subject_id: int, hadm_id: int) -> dict:
    series = admission_series(con, subject_id, hadm_id)
    if not series:
        return {"found": False,
                "message": f"No admission {hadm_id} for patient {subject_id}."}
    states = _states_for(series)
    risk = score_admission(states)
    span = con.execute(
        "SELECT span_hours, n_measurements FROM admissions WHERE subject_id=? AND hadm_id=?",
        [subject_id, hadm_id]).fetchone()
    return {
        "found": True,
        "subject_id": subject_id,
        "hadm_id": hadm_id,
        "risk_score": risk.score,
        "risk_category": risk.category,
        "n_measurements": span[1] if span else None,
        "span_hours": span[0] if span else None,
        "contributions": risk.contributions,
        "alerts": build_alerts(risk),
        "syndromes": detect_syndromes(states),
    }


def _get_alerts(con, subject_id: int, hadm_id: int, last_n_days: int | None = None) -> dict:
    """Early-warning alerts for an admission. `last_n_days` restricts the lab
    history considered to the most recent window (anchored to this admission)."""
    series = admission_series(con, subject_id, hadm_id)
    if not series:
        return {"found": False,
                "message": f"No admission {hadm_id} for patient {subject_id}."}

    if last_n_days and last_n_days > 0:
        clause, params = _window_clause(con, subject_id, hadm_id, last_n_days)
        rows = con.execute(f"""
            SELECT itemid, test_name, unit, charttime, value
            FROM labs_clean
            WHERE subject_id = ? AND hadm_id = ?{clause}
            ORDER BY itemid, charttime
        """, [subject_id, hadm_id] + params).fetchall()
        windowed: dict = {}
        for itemid, name, unit, t, v in rows:
            d = windowed.setdefault(itemid, {"test_name": name, "unit": unit, "points": []})
            d["points"].append((t, v))
        series = windowed or series

    states = _states_for(series)
    risk = score_admission(states)
    return {
        "found": True, "subject_id": subject_id, "hadm_id": hadm_id,
        "window_days": last_n_days,
        "risk_score": risk.score, "risk_category": risk.category,
        "alerts": build_alerts(risk),
    }


def _make_get_lab_series(con, charts: list):
    def get_lab_series(subject_id: int, hadm_id: int, lab_name: str,
                       last_n_days: int | None = None, render_chart: bool = True) -> dict:
        """Time-series of one lab for an admission, optionally windowed to the most
        recent days. Set render_chart=True to also show the user an inline graph."""
        itemid = _resolve_lab(lab_name)
        if itemid is None:
            return {"found": False, "requested": lab_name,
                    "message": (f"'{lab_name}' is not tracked by this system. "
                                "Tracked labs: " +
                                ", ".join(d.name for d in LAB_DEFS.values()) + ".")}
        d = LAB_DEFS[itemid]
        clause, params = _window_clause(con, subject_id, hadm_id, last_n_days)
        rows = con.execute(f"""
            SELECT charttime, value FROM labs_clean
            WHERE subject_id = ? AND hadm_id = ? AND itemid = ?{clause}
            ORDER BY charttime
        """, [subject_id, hadm_id, itemid] + params).fetchall()
        if not rows:
            return {"found": False, "test_name": d.name,
                    "message": (f"No {d.name} measurements for patient {subject_id}, "
                                f"admission {hadm_id}"
                                + (f" in the last {last_n_days} days." if last_n_days else "."))}
        points = [{"time": t.isoformat(), "value": v} for (t, v) in rows]
        values = [v for (_, v) in rows]
        result = {
            "found": True, "test_name": d.name, "unit": d.unit,
            "normal_low": d.low, "normal_high": d.high,
            "n_points": len(points),
            "first_value": values[0], "latest_value": values[-1],
            "min": min(values), "max": max(values),
            "window_days": last_n_days,
            # cap what we hand the model so a long stay doesn't blow up the prompt
            "points": points if len(points) <= 60 else points[-60:],
        }
        if render_chart:
            charts.append({
                "title": f"{d.name} — Patient {subject_id} (Adm {hadm_id})",
                "test_name": d.name, "unit": d.unit,
                "normal_low": d.low, "normal_high": d.high,
                "points": points,
            })
        return result
    return get_lab_series


def _cohort_stats(con) -> dict:
    pipeline = dict(con.execute("SELECT metric, value FROM pipeline_stats").fetchall())
    dist = dict(con.execute(
        "SELECT category, COUNT(*) FROM risk_summary GROUP BY category").fetchall())
    return {"pipeline": pipeline, "risk_distribution": dist}


def _list_high_risk(con, category: str | None = None, limit: int = 10) -> dict:
    """Triage list of admissions ranked by risk score (highest first)."""
    limit = max(1, min(int(limit or 10), 50))
    where, params = "", []
    if category in ("Low", "Medium", "High"):
        where, params = "WHERE r.category = ?", [category]
    rows = con.execute(f"""
        SELECT r.subject_id, r.hadm_id, r.score, r.category,
               r.n_high, r.n_worsening, a.n_measurements, a.span_hours
        FROM risk_summary r JOIN admissions a USING (subject_id, hadm_id)
        {where}
        ORDER BY r.score DESC
        LIMIT ?
    """, params + [limit]).fetchall()
    cols = ["subject_id", "hadm_id", "risk_score", "risk_category",
            "n_critical_labs", "n_worsening_labs", "n_measurements", "span_hours"]
    return {"count": len(rows), "category": category or "All",
            "patients": [dict(zip(cols, r)) for r in rows]}


def build_toolset(con, charts: list) -> list:
    """Return the list of callables exposed to the agent for one request.

    `con` is a read-only connection; `charts` is the request-scoped list that
    chart-producing tools append to. The Gemini SDK reads each callable's name,
    signature and docstring to build its function declaration.
    """
    def list_available_labs() -> dict:
        """List the 8 lab tests this system tracks, with units and normal ranges.
        Call this to check whether a lab the user asked about exists at all."""
        return _list_available_labs()

    def find_patient(subject_id: int) -> dict:
        """Look up a patient by SUBJECT_ID and list their hospital admissions with
        each admission's risk score/category. Use this first when the user gives a
        patient id, to discover the admission (HADM_ID) to drill into."""
        return _find_patient(con, subject_id)

    def get_admission_detail(subject_id: int, hadm_id: int) -> dict:
        """Full risk picture for one admission: overall risk score & category,
        per-lab status/trend breakdown, early-warning alerts and detected clinical
        syndromes. Use for 'is this patient at risk / what's wrong' questions."""
        return _get_admission_detail(con, subject_id, hadm_id)

    def get_alerts(subject_id: int, hadm_id: int, last_n_days: int = 0) -> dict:
        """Early-warning alerts (risk points / worsening labs) for an admission.
        Pass last_n_days > 0 to restrict to the most recent N days of that
        admission (anchored to the patient's latest measurement)."""
        return _get_alerts(con, subject_id, hadm_id, last_n_days or None)

    def cohort_stats() -> dict:
        """Dataset-wide stats: pipeline scale (rows, patients, admissions) and the
        Low/Medium/High risk distribution. Use for 'how many high-risk patients'
        or 'how big is the dataset' questions."""
        return _cohort_stats(con)

    def list_high_risk_patients(category: str = "", limit: int = 10) -> dict:
        """Top admissions ranked by risk score. Optionally filter category to
        'High', 'Medium' or 'Low'. Use to surface concrete patient/admission ids
        the user can then ask about."""
        return _list_high_risk(con, category or None, limit)

    return [list_available_labs, find_patient, get_admission_detail,
            get_alerts, _make_get_lab_series(con, charts),
            cohort_stats, list_high_risk_patients]
