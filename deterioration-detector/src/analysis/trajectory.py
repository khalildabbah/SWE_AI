"""
RISK TRAJECTORY (the headline visual)
=====================================
Recompute the admission's risk score at each point in time, so the dashboard can
plot risk as a rising/falling curve across the stay -- directly answering
"can lab trends over time reveal deterioration?".

Walks every measurement in chronological order, keeping the latest value of each
lab plus its recent window, and re-scores after each new measurement.
"""
from collections import defaultdict, deque

from src.analysis.risk_score import LabState, score_admission

WINDOW = 3


def compute_trajectory(series: dict) -> list[dict]:
    """
    series: {itemid: {"test_name","unit","points":[(charttime,value)...]}}
    returns: [{"time": iso, "score": int, "category": str}, ...] over time
    """
    # flatten to one timeline of (time, itemid, value), oldest first
    events = []
    for itemid, info in series.items():
        for (t, v) in info["points"]:
            events.append((t, itemid, v, info["test_name"], info["unit"]))
    events.sort(key=lambda e: e[0])

    recent = defaultdict(lambda: deque(maxlen=WINDOW))
    meta = {}
    traj = []
    for (t, itemid, v, name, unit) in events:
        recent[itemid].append(v)
        meta[itemid] = (name, unit)
        states = [
            LabState(itemid=i, test_name=meta[i][0], unit=meta[i][1],
                     latest_value=vals[-1], series=list(vals))
            for i, vals in recent.items()
        ]
        r = score_admission(states)
        traj.append({"time": t.isoformat(), "score": r.score, "category": r.category})
    return traj
