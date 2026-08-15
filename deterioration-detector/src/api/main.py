"""
FASTAPI BACKEND
===============
Serves the triage board, per-admission lab timelines, risk score, risk
trajectory, and alerts to the React dashboard.

Run:  uvicorn src.api.main:app --reload  (from the project root)
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.storage.db import connect, admission_series
from src.storage import pattern_risk
from src.analysis.risk_score import LabState, score_admission, score_pattern
from src.analysis.custom_syndromes import get_custom
from src.analysis.alerts import build_alerts
from src.analysis.trajectory import compute_trajectory
from src.analysis.syndromes import detect_syndromes
from src.analysis.custom_syndromes import detect_custom
from src.analysis.evaluation import confusion_metrics
from src.analysis.lead_time import compute_lead_time
from src.analysis.rules import build_rules
from src.ingestion.lab_dictionary import LAB_DEFS
from src.api.chat import router as chat_router
from src.api.builder import router as builder_router

app = FastAPI(title="Patient Deterioration Detector", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Grounded dataset Q&A chatbot (OpenAI) — POST /api/chat
app.include_router(chat_router)
# Pattern Builder: AI-assisted, web-searched custom syndromes — /api/builder/*
app.include_router(builder_router)


@app.get("/api/stats")
def stats():
    """Pipeline scale story + risk distribution for the dashboard header."""
    con = connect()
    pipeline = dict(con.execute("SELECT metric, value FROM pipeline_stats").fetchall())
    dist = dict(con.execute(
        "SELECT category, COUNT(*) FROM risk_summary GROUP BY category").fetchall())
    con.close()
    return {"pipeline": pipeline, "risk_distribution": dist}


@app.get("/api/evaluation")
def evaluation():
    """Detector-vs-MIMIC-FLAG accuracy: overall + per-lab confusion metrics."""
    con = connect()
    try:
        rows = con.execute(
            "SELECT itemid, test_name, tp, fp, fn, tn FROM flag_eval ORDER BY test_name"
        ).fetchall()
    except Exception:
        # older DB built before this feature -> tell the client to rebuild
        con.close()
        raise HTTPException(503, "Evaluation not available — re-run scripts/build_risk.py")
    con.close()
    if not rows:
        raise HTTPException(503, "Evaluation not available — re-run scripts/build_risk.py")

    per_lab = []
    agg = [0, 0, 0, 0]  # tp, fp, fn, tn
    for itemid, name, tp, fp, fn, tn in rows:
        agg = [agg[0] + tp, agg[1] + fp, agg[2] + fn, agg[3] + tn]
        per_lab.append({"itemid": itemid, "test_name": name,
                        **confusion_metrics(tp, fp, fn, tn)})
    return {
        "overall": confusion_metrics(*agg),
        "per_lab": per_lab,
        # surfaced in the UI so the numbers are read honestly
        "note": ("Scored against MIMIC's own 'abnormal' FLAG as ground truth. "
                 "Disagreements arise where our generic adult reference ranges "
                 "differ from each lab's originating reference interval — "
                 "informative, not clinical validation."),
    }


@app.get("/api/rules")
def rules():
    """
    The transparent rule book behind every score: reference ranges, the
    normal/abnormal/critical banding, the point math, the Low/Medium/High
    cut-points, and the syndrome definitions — each tagged with a published
    source. Derived live from the scoring engine so it can never drift.
    """
    return build_rules()


@app.get("/api/lead-time")
def lead_time():
    """
    Cohort early-warning story: how many hours before the first critical lab
    value our risk score escalated. Reported at two thresholds — "first concern"
    (Medium+) and "high risk" (High). Precomputed in build_risk.py.
    """
    con = connect()
    try:
        n_det = con.execute(
            "SELECT SUM(CASE WHEN deteriorated THEN 1 ELSE 0 END) FROM lead_time"
        ).fetchone()[0]
        bands = {}
        for key, lead_col, flag_col in (
            ("concern", "lead_concern_hours", "concerned"),
            ("alert", "lead_alert_hours", "alerted"),
        ):
            bands[key] = con.execute(f"""
                SELECT
                    SUM(CASE WHEN deteriorated AND {flag_col} AND {lead_col} > 0
                             THEN 1 ELSE 0 END),
                    median({lead_col}) FILTER (
                        WHERE deteriorated AND {flag_col} AND {lead_col} > 0),
                    quantile_cont({lead_col}, 0.75) FILTER (
                        WHERE deteriorated AND {flag_col} AND {lead_col} > 0),
                    max({lead_col}) FILTER (
                        WHERE deteriorated AND {flag_col} AND {lead_col} > 0)
                FROM lead_time
            """).fetchone()
    except Exception:
        con.close()
        raise HTTPException(503, "Lead-time not available — re-run scripts/build_risk.py")
    con.close()

    if not n_det:
        raise HTTPException(503, "Lead-time not available — re-run scripts/build_risk.py")

    rnd = lambda x: None if x is None else round(x, 1)

    def band(row):
        n_early = row[0] or 0
        return {
            "n_early_warning": n_early,
            "early_warning_rate": round(100 * n_early / n_det, 1),
            "median_lead_hours": rnd(row[1]),
            "p75_lead_hours": rnd(row[2]),
            "max_lead_hours": rnd(row[3]),
        }

    return {
        "n_deteriorated": n_det,
        "concern": band(bands["concern"]),   # first time score left Low (Medium+)
        "alert": band(bands["alert"]),        # first time score reached High
        "note": ("'Deterioration' here is a lab-based proxy — the first critically "
                 "out-of-range value — because this prototype ingests only LABEVENTS "
                 "(no death/ICU-transfer outcomes). Lead time is how many hours earlier "
                 "the trend-aware score escalated. A proxy measure, not clinical "
                 "validation."),
    }


def _active_pattern(key: str | None) -> dict | None:
    """Resolve ?pattern=<key> to a saved pattern, or None for the built-in score.

    An unknown or untestable key falls back to the built-in score rather than
    erroring — a stale bookmark should not break the dashboard.
    """
    if not key:
        return None
    pattern = get_custom(key)
    if not pattern:
        return None
    runnable = [s for s in (pattern.get("signals") or [])
                if s.get("in_dataset") and s.get("itemid") is not None]
    return pattern if runnable else None


@app.get("/api/admissions")
def admissions(
    category: str | None = Query(None, pattern="^(Low|Medium|High)$"),
    sort: str = Query("score", pattern="^(score|measurements)$"),
    limit: int = Query(50, le=500),
    offset: int = 0,
    pattern: str | None = None,
):
    """Triage board: admissions ranked by risk (precomputed).

    With `pattern` set, ranks by that user-built pattern's score instead of the
    built-in one, reading the per-pattern ranking cached by `pattern_risk`.
    """
    active = _active_pattern(pattern)
    con = connect()
    try:
        if active:
            pattern_risk.ensure_built(active)
            table = pattern_risk.attach(con)
            if table:
                where = "WHERE r.pattern_key = ?" + (" AND r.category = ?" if category else "")
                params = [active["key"]] + ([category] if category else [])
                # A total order: score alone ties for thousands of rows, and without a
                # tiebreaker LIMIT/OFFSET paging repeats some rows and skips others.
                order = (("r.score DESC" if sort == "score" else "a.n_measurements DESC")
                         + ", r.subject_id, r.hadm_id")
                rows = con.execute(f"""
                    SELECT r.subject_id, r.hadm_id, r.score, r.category,
                           r.n_high, r.n_worsening, a.n_measurements, a.span_hours
                    FROM {table} r
                    JOIN admissions a USING (subject_id, hadm_id)
                    {where}
                    ORDER BY {order}
                    LIMIT ? OFFSET ?
                """, params + [limit, offset]).fetchall()
                total = con.execute(
                    f"SELECT COUNT(*) FROM {table} r {where}", params).fetchone()[0]
                cols = ["subject_id", "hadm_id", "score", "category",
                        "n_high", "n_worsening", "n_measurements", "span_hours"]
                return {"total": total, "pattern": active["key"],
                        "pattern_name": active["name"],
                        "items": [dict(zip(cols, r)) for r in rows]}

        where = "WHERE r.category = ?" if category else ""
        params = [category] if category else []
        # A total order: score alone ties for thousands of rows, and without a
        # tiebreaker LIMIT/OFFSET paging repeats some rows and skips others.
        order = (("r.score DESC" if sort == "score" else "a.n_measurements DESC")
                 + ", r.subject_id, r.hadm_id")
        rows = con.execute(f"""
            SELECT r.subject_id, r.hadm_id, r.score, r.category,
                   r.n_high, r.n_worsening, a.n_measurements, a.span_hours
            FROM risk_summary r
            JOIN admissions a USING (subject_id, hadm_id)
            {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
        total = con.execute(
            f"SELECT COUNT(*) FROM risk_summary r {where}", params).fetchone()[0]
    finally:
        con.close()
    cols = ["subject_id", "hadm_id", "score", "category",
            "n_high", "n_worsening", "n_measurements", "span_hours"]
    return {"total": total, "pattern": None,
            "items": [dict(zip(cols, r)) for r in rows]}


@app.get("/api/admissions/{subject_id}/{hadm_id}")
def admission_detail(subject_id: int, hadm_id: int, pattern: str | None = None):
    """Full detail for one admission: lab timelines, risk, trajectory, alerts.

    With `pattern` set, the risk score, category, alerts and trajectory are all
    computed from that user-built pattern instead of the built-in 8-lab score.
    """
    active = _active_pattern(pattern)
    con = connect()
    series = admission_series(con, subject_id, hadm_id)
    con.close()
    if not series:
        raise HTTPException(404, "Admission not found")

    # build current state (last value + recent window) per lab
    states, lab_series = [], []
    for itemid, info in series.items():
        d = LAB_DEFS[itemid]
        values = [v for (_, v) in info["points"]]
        states.append(LabState(
            itemid=itemid, test_name=info["test_name"], unit=info["unit"],
            latest_value=values[-1], series=values,
        ))
        lab_series.append({
            "itemid": itemid,
            "test_name": info["test_name"],
            "unit": info["unit"],
            "normal_low": d.low,
            "normal_high": d.high,
            "points": [{"time": t.isoformat(), "value": v} for (t, v) in info["points"]],
        })

    signals = [s for s in (active.get("signals") or [])
               if s.get("in_dataset") and s.get("itemid") is not None] if active else []
    risk = score_pattern(states, signals) if active else score_admission(states)
    lt = compute_lead_time(series)
    return {
        "subject_id": subject_id,
        "hadm_id": hadm_id,
        "risk": {"score": risk.score, "category": risk.category,
                 "contributions": risk.contributions,
                 # what produced this score, so the UI never mislabels it
                 "pattern": active["key"] if active else None,
                 "pattern_name": active["name"] if active else None,
                 "max_score": 3 * len(signals) if active else None},
        "alerts": build_alerts(risk),
        # Built-in syndromes and the user's own Pattern Builder patterns share a
        # card on the dashboard, so they share a list and an ordering.
        "syndromes": sorted(
            detect_syndromes(states) + detect_custom(states),
            key=lambda r: (r["confidence"], r["severity"] == "critical"), reverse=True),
        "trajectory": compute_trajectory(series, signals or None),
        "lead_time": {
            "deteriorated": lt.deteriorated, "concerned": lt.concerned,
            "alerted": lt.alerted,
            "event_hours": lt.event_hours, "concern_hours": lt.concern_hours,
            "alert_hours": lt.alert_hours,
            "lead_concern_hours": lt.lead_concern_hours,
            "lead_alert_hours": lt.lead_alert_hours,
            "event_lab": lt.event_lab, "event_time": lt.event_time,
            "concern_time": lt.concern_time, "alert_time": lt.alert_time,
        },
        "labs": lab_series,
    }


# Serve the built React dashboard from the same origin as the API.
# Mounted LAST so it never shadows the /api/* routes above. `html=True` makes
# StaticFiles fall back to index.html, so client-side routing / deep links work.
# Guarded so local dev (no `npm run build` yet) doesn't fail to start.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
