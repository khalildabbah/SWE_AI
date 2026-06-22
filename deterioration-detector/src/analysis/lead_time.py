"""
EARLY-WARNING LEAD TIME (the scientific core)
=============================================
The whole premise of this project is that lab *trends* surface deterioration
"hours before" it becomes clinically obvious. The risk trajectory shows the
score rising over time, but on its own it never quantifies the headline claim.
This module does.

For one admission we walk its measurements in chronological order and find three
moments:

  * CONCERN -- the first time the running risk score leaves Low (reaches Medium
             or High). This is the earliest hint of trouble.
  * ALERT  -- the first time the score reaches High. This is when the dashboard
             puts the patient at the top of the triage board.
  * EVENT  -- the first time any single lab value is CRITICAL (far outside its
             reference range). This is the proxy for "deterioration is now
             obvious from the labs alone".

LEAD TIME = EVENT - CONCERN (or EVENT - ALERT). When the score escalates before
the first critical value (lead > 0) it gave genuine early warning; how many
hours of warning is exactly the number this project is about. We report both the
softer "first concern" lead and the stricter "high-risk" lead, because our rule
score weights critical values heavily -- so High often coincides with the event
while the first *concern* tends to precede it.

Why a lab-based event proxy? This prototype only ingests MIMIC's LABEVENTS, so
real outcomes (death, ICU transfer) aren't available -- the first critical lab
is the most defensible "obvious deterioration" signal we can derive from the
data we have. It is a proxy, not a clinical outcome (see the disclaimer in the
README). Like the rest of src/analysis this is a pure, unit-tested rule layer.
"""
from collections import defaultdict, deque
from dataclasses import dataclass

from src.analysis.abnormal import classify, CRITICAL
from src.analysis.risk_score import LabState, score_admission, LOW, MEDIUM, HIGH

WINDOW = 3  # same recent-window the trend detector and trajectory use

# rank so "reach at least this category" is well defined
_RANK = {LOW: 0, MEDIUM: 1, HIGH: 2}


@dataclass
class LeadTimeResult:
    """Per-admission early-warning summary, all times in hours from first lab."""
    deteriorated: bool        # at least one lab value reached CRITICAL
    concerned: bool           # risk score left Low (reached Medium or High)
    alerted: bool             # risk score reached High
    event_hours: float | None      # hours from first lab to first critical value
    concern_hours: float | None    # hours from first lab to first Medium+ score
    alert_hours: float | None      # hours from first lab to first High score
    lead_concern_hours: float | None  # event - concern (>0 = warned early)
    lead_alert_hours: float | None    # event - alert  (>0 = warned early)
    event_lab: str | None          # lab whose value first went critical
    event_time: str | None         # ISO timestamp of the deterioration event
    concern_time: str | None       # ISO timestamp of the first concern
    alert_time: str | None         # ISO timestamp of the first High alert


def compute_lead_time(series: dict) -> LeadTimeResult:
    """
    series: {itemid: {"test_name","unit","points":[(charttime, value)...]}}
            (same shape produced by storage.db.admission_series)

    Returns when our score first escalated (concern = Medium+, alert = High) vs
    when the first critical value appeared, and the lead time between them.
    """
    # flatten to one timeline of measurements, oldest first (mirrors trajectory)
    events = []
    for itemid, info in series.items():
        for (t, v) in info["points"]:
            events.append((t, itemid, v, info["test_name"], info["unit"]))
    if not events:
        return LeadTimeResult(False, False, False,
                              None, None, None, None, None, None, None, None, None)
    events.sort(key=lambda e: e[0])
    t0 = events[0][0]

    recent = defaultdict(lambda: deque(maxlen=WINDOW))
    meta = {}
    concern_hours = concern_time = None
    alert_hours = alert_time = None
    event_hours = event_time = event_lab = None

    for (t, itemid, v, name, unit) in events:
        recent[itemid].append(v)
        meta[itemid] = (name, unit)
        hrs = (t - t0).total_seconds() / 3600.0

        # deterioration event: first time any value is critically out of range
        if event_hours is None and classify(itemid, v) == CRITICAL:
            event_hours, event_time, event_lab = hrs, t.isoformat(), name

        # score the running state only while a threshold is still unmet (cheap)
        if concern_hours is None or alert_hours is None:
            states = [
                LabState(i, meta[i][0], meta[i][1], vals[-1], list(vals))
                for i, vals in recent.items()
            ]
            rank = _RANK[score_admission(states).category]
            if concern_hours is None and rank >= _RANK[MEDIUM]:
                concern_hours, concern_time = hrs, t.isoformat()
            if alert_hours is None and rank >= _RANK[HIGH]:
                alert_hours, alert_time = hrs, t.isoformat()

        if alert_hours is not None and event_hours is not None:
            break

    concerned = concern_hours is not None
    alerted = alert_hours is not None
    deteriorated = event_hours is not None
    rnd = lambda x: None if x is None else round(x, 2)
    lead_concern = (round(event_hours - concern_hours, 2)
                    if concerned and deteriorated else None)
    lead_alert = (round(event_hours - alert_hours, 2)
                  if alerted and deteriorated else None)
    return LeadTimeResult(
        deteriorated=deteriorated, concerned=concerned, alerted=alerted,
        event_hours=rnd(event_hours), concern_hours=rnd(concern_hours),
        alert_hours=rnd(alert_hours),
        lead_concern_hours=lead_concern, lead_alert_hours=lead_alert,
        event_lab=event_lab, event_time=event_time,
        concern_time=concern_time, alert_time=alert_time,
    )
