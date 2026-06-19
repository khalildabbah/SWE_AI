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
from src.analysis.risk_score import LabState, score_admission
from src.analysis.alerts import build_alerts
from src.analysis.trajectory import compute_trajectory
from src.ingestion.lab_dictionary import LAB_DEFS

app = FastAPI(title="Patient Deterioration Detector", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/stats")
def stats():
    """Pipeline scale story + risk distribution for the dashboard header."""
    con = connect()
    pipeline = dict(con.execute("SELECT metric, value FROM pipeline_stats").fetchall())
    dist = dict(con.execute(
        "SELECT category, COUNT(*) FROM risk_summary GROUP BY category").fetchall())
    con.close()
    return {"pipeline": pipeline, "risk_distribution": dist}


@app.get("/api/admissions")
def admissions(
    category: str | None = Query(None, pattern="^(Low|Medium|High)$"),
    sort: str = Query("score", pattern="^(score|measurements)$"),
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    """Triage board: admissions ranked by risk (precomputed)."""
    con = connect()
    where = "WHERE r.category = ?" if category else ""
    params = [category] if category else []
    order = "r.score DESC" if sort == "score" else "a.n_measurements DESC"
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
    con.close()
    cols = ["subject_id", "hadm_id", "score", "category",
            "n_high", "n_worsening", "n_measurements", "span_hours"]
    return {"total": total, "items": [dict(zip(cols, r)) for r in rows]}


@app.get("/api/admissions/{subject_id}/{hadm_id}")
def admission_detail(subject_id: int, hadm_id: int):
    """Full detail for one admission: lab timelines, risk, trajectory, alerts."""
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

    risk = score_admission(states)
    return {
        "subject_id": subject_id,
        "hadm_id": hadm_id,
        "risk": {"score": risk.score, "category": risk.category,
                 "contributions": risk.contributions},
        "alerts": build_alerts(risk),
        "trajectory": compute_trajectory(series),
        "labs": lab_series,
    }


# Serve the built React dashboard from the same origin as the API.
# Mounted LAST so it never shadows the /api/* routes above. `html=True` makes
# StaticFiles fall back to index.html, so client-side routing / deep links work.
# Guarded so local dev (no `npm run build` yet) doesn't fail to start.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
