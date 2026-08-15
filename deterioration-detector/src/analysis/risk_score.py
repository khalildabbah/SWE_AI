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

from src.analysis.abnormal import classify, points, rule_bound, rule_fires
from src.analysis.trends import WORSENING, trend

LOW, MEDIUM, HIGH = "Low", "Medium", "High"

# Most one rule can contribute: 2 severity points (critical) + 1 worsening.
MAX_POINTS_PER_RULE = 3


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


# ── Scoring by a user-built pattern ──────────────────────────────────────────

def _matches_direction(itemid: int, value: float, direction: str,
                       threshold: float | None = None) -> bool:
    """Does the rule fire — at its own threshold, or the reference range?"""
    return rule_fires(itemid, value, direction, threshold)


def categorize_for_max(score: int, max_score: int) -> str:
    """Low/Medium/High scaled to the most a given pattern could score.

    The built-in bands (0-2 / 3-5 / 6+) assume eight labs are in play. A two-rule
    pattern tops out at 6 points, so those bands would call almost everything
    Low. Scoring the top third of a pattern's own ceiling as High keeps the
    badge meaningful whether the pattern has two rules or six.
    """
    if max_score <= 0:
        return LOW
    if score >= (2 * max_score) / 3:
        return HIGH
    if score >= max_score / 3:
        return MEDIUM
    return LOW


def score_pattern(states: list[LabState], signals: list[dict]) -> RiskResult:
    """Score one admission against a user-built pattern's rules.

    `signals` are cleaned pattern rules ({itemid, name, direction, in_dataset});
    rules over labs this dataset doesn't carry are ignored, since there is
    nothing to measure. Returns the same RiskResult shape as `score_admission`,
    so every consumer — the badge, the trajectory, the alerts — works unchanged.
    """
    by_id = {st.itemid: st for st in states}
    runnable = [s for s in signals if s.get("in_dataset") and s.get("itemid") is not None]

    score = 0
    contributions = []
    for sig in runnable:
        itemid, direction = sig["itemid"], sig["direction"]
        st = by_id.get(itemid)
        if st is None:
            continue  # this admission never had the lab drawn

        # A lab moving the way the pattern does NOT care about is not evidence
        # for the syndrome, so it contributes nothing at all.
        threshold = sig.get("threshold")
        on_side = _matches_direction(itemid, st.latest_value, direction, threshold)
        status = classify(itemid, st.latest_value)
        # the pattern's own direction decides what "getting worse" means here
        tr = trend(itemid, st.series, worsening=direction)
        # Severity stays anchored to the reference range: how abnormal a value is
        # clinically does not change because the rule set a stricter threshold.
        # A rule that fired is always worth something though, so a threshold
        # LOOSER than the range can't match and still score zero.
        sev_pts = max(1, points(itemid, st.latest_value)) if on_side else 0
        trend_pts = 1 if (on_side and tr == WORSENING) else 0
        lab_total = sev_pts + trend_pts
        score += lab_total
        contributions.append({
            "itemid": itemid,
            "test_name": st.test_name,
            "unit": st.unit,
            "latest_value": st.latest_value,
            "status": status if on_side else "normal",
            "trend": tr,
            "points": lab_total,
            "direction": direction,
            "matched": on_side,
            "threshold": threshold,
            "bound": rule_bound(itemid, direction, threshold),
        })

    contributions.sort(key=lambda c: c["points"], reverse=True)
    max_score = MAX_POINTS_PER_RULE * len(runnable)
    return RiskResult(score=score, category=categorize_for_max(score, max_score),
                      contributions=contributions)
