"""
M5 RISK SCORE
=============
Combine per-lab severity (M4) and per-lab trend (M3) into a single, explainable
risk score and a Low / Medium / High category for an admission.

The score is intentionally a transparent rule engine (not a black-box model) so
it can be explained in the seminar and unit-tested. Phase C can swap a learned
model behind the same `score_admission` interface.

TWO SCORING MODES
-----------------
`score_admission()` is the default: every tracked lab counts, equally, in
whichever direction the lab dictionary calls clinically bad. It answers "how
much of this patient's blood work looks wrong?".

`score_pattern()` answers a different question — "how much does this patient
look like THIS syndrome?" — by scoring only the labs a user-built pattern names,
and only when they move in the direction that pattern cares about. The point
maths is deliberately identical (severity 0/1/2 plus a worsening bonus), so a
pattern score is read the same way as the built-in one and the Scoring Rule Book
stays truthful. Only two things differ, both necessarily:
  * a lab moving the "wrong" way for the pattern scores nothing, and
  * Low/Medium/High are scaled to what that pattern can actually produce, since
    a 2-rule pattern could never reach the built-in score's High band.
"""
from dataclasses import dataclass, field

from src.analysis.abnormal import classify, points
from src.analysis.trends import WORSENING, trend
# The pattern half of the scoring lives in its own module so that one executor
# serves every caller. Re-exported here because `LabState`, the category names
# and the scaled-band helper are imported from `risk_score` all over the app.
from src.analysis.pattern_engine import (  # noqa: F401  (re-exported)
    LabState, PatternResult, evaluate_pattern, categorize_for_max,
    LOW, MEDIUM, HIGH, MAX_POINTS_PER_RULE,
)


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


# ── Scoring by a user-built pattern ──────────────────────────

def score_pattern(states: list[LabState], signals: list[dict]) -> RiskResult:
    """Score one admission against a user-built pattern's rules.

    A thin adapter: `pattern_engine.evaluate_pattern` does the deciding, this
    reshapes its result into the `RiskResult` that the badge, the alerts and the
    trajectory already consume. Keeping the maths in one place is what stops the
    score disagreeing with the card and the cohort run about the same pattern.
    """
    result = evaluate_pattern(states, signals)
    contributions = [
        {
            "itemid": r.itemid,
            "test_name": r.name,
            "unit": r.unit,
            "latest_value": r.value,
            "status": r.status,
            "trend": r.trend,
            "points": r.points,
            "direction": r.direction,
            "matched": r.fired,
            "threshold": r.threshold,
            "bound": r.bound,
        }
        # a lab that was never drawn has nothing to report
        for r in result.testable_rules if r.value is not None
    ]
    # biggest drivers first
    contributions.sort(key=lambda c: c["points"], reverse=True)
    return RiskResult(score=result.score, category=result.category,
                      contributions=contributions)
