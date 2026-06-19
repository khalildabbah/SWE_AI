"""
M5 RISK SCORE
=============
Combine per-lab severity (M4) and per-lab trend (M3) into a single, explainable
risk score and a Low / Medium / High category for an admission.

The score is intentionally a transparent rule engine (not a black-box model) so
it can be explained in the seminar and unit-tested. Phase C can swap a learned
model behind the same `score_admission` interface.
"""
from dataclasses import dataclass, field

from src.analysis.abnormal import classify, points
from src.analysis.trends import WORSENING, trend

LOW, MEDIUM, HIGH = "Low", "Medium", "High"


@dataclass
class LabState:
    """Computed state of one lab within an admission (newest value + its history)."""
    itemid: int
    test_name: str
    unit: str
    latest_value: float
    series: list[float] = field(default_factory=list)  # oldest -> newest


@dataclass
class RiskResult:
    score: int
    category: str
    contributions: list[dict]  # per-lab breakdown for explainability


def categorize(score: int) -> str:
    if score <= 2:
        return LOW
    if score <= 5:
        return MEDIUM
    return HIGH


def score_admission(states: list[LabState]) -> RiskResult:
    """Score one admission from the current state of each of its labs."""
    score = 0
    contributions = []
    for st in states:
        sev_pts = points(st.itemid, st.latest_value)
        status = classify(st.itemid, st.latest_value)
        tr = trend(st.itemid, st.series)
        # a worsening trend only adds risk once the value is already out of range,
        # so small in-range fluctuations don't inflate the score
        trend_pts = 1 if (tr == WORSENING and status != "normal") else 0
        lab_total = sev_pts + trend_pts
        score += lab_total
        contributions.append({
            "itemid": st.itemid,
            "test_name": st.test_name,
            "unit": st.unit,
            "latest_value": st.latest_value,
            "status": status,
            "trend": tr,
            "points": lab_total,
        })
    # sort so the biggest drivers surface first
    contributions.sort(key=lambda c: c["points"], reverse=True)
    return RiskResult(score=score, category=categorize(score), contributions=contributions)
