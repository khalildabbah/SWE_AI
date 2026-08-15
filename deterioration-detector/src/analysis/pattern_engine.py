"""
PATTERN ENGINE
==============
The one place that answers "apply THIS pattern to THIS admission".

A user-built pattern is used in four different settings — a card on the patient
page, a run across the whole cohort, the triage board's ranking, and the risk
score itself. Each of those used to decide for itself what "the pattern matched"
meant, which is precisely how they drift: at one point the board ranked an
admission that the card refused to show and the cohort run excluded, because one
path forgot the pattern's own `min_signals` threshold.

So the decision lives here, once, and the four callers became presentation. If
you want to know whether the code does what a pattern says, there is exactly one
function to read.

`evaluate_pattern()` deliberately returns the whole derivation rather than a
verdict: every rule, the value it was tested against, the bound it was tested
at, whether it fired and what it contributed. Callers filter that down to
whatever they display; nobody has to recompute anything to explain a result.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.abnormal import classify, points, rule_bound, rule_fires
from src.analysis.trends import WORSENING, trend

LOW, MEDIUM, HIGH = "Low", "Medium", "High"

# Most one rule can contribute: 2 severity points (critical) + 1 worsening.
MAX_POINTS_PER_RULE = 3

# Bumped when a change alters what counts as a match, so a ranking cache built
# by older code is treated as absent instead of silently served.
CRITERIA_VERSION = 2


@dataclass
class LabState:
    """Computed state of one lab within an admission (newest value + its history).

    Lives here rather than in risk_score because the engine is the thing that
    consumes it; risk_score re-exports the name so existing imports still work.
    """
    itemid: int
    test_name: str
    unit: str
    latest_value: float
    series: list[float] = field(default_factory=list)  # oldest -> newest


@dataclass(frozen=True)
class RuleOutcome:
    """One pattern rule, evaluated — including the rules that did NOT fire.

    `bound` is the number the rule was actually tested at, so a result can always
    be read back as "value {direction} bound -> fired".
    """
    itemid: int | None
    name: str
    direction: str
    testable: bool             # False -> lab absent from this dataset
    threshold: float | None    # the rule's own cut-off, None = reference range
    bound: float | None        # what it was tested at (threshold or range edge)
    value: float | None        # None -> the lab was never drawn for this patient
    unit: str
    fired: bool
    status: str                # normal | abnormal | critical
    trend: str                 # worsening | improving | stable
    points: int


@dataclass(frozen=True)
class PatternResult:
    """The full derivation of applying one pattern to one admission."""
    rules: list                       # list[RuleOutcome], every rule
    n_testable: int
    n_fired: int
    requested_min_signals: int
    min_signals: int                  # after capping to what is testable
    matched: bool
    score: int
    max_score: int
    category: str

    @property
    def fired_rules(self) -> list:
        return [r for r in self.rules if r.fired]

    @property
    def testable_rules(self) -> list:
        return [r for r in self.rules if r.testable]

    @property
    def research_only_rules(self) -> list:
        return [r for r in self.rules if not r.testable]


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


def effective_min_signals(requested, n_testable: int) -> int:
    """How many rules must fire, given how many can actually be tested.

    A pattern may ask for more agreement than this dataset can supply — three
    rules where only two labs exist here. Capping keeps the pattern evaluable
    instead of unsatisfiable, and doing it in one place is what stops the cohort
    run and the patient card disagreeing about the same pattern.
    """
    try:
        requested = int(requested or 1)
    except (TypeError, ValueError):
        requested = 1
    if n_testable <= 0:
        return max(1, requested)
    return max(1, min(requested, n_testable))


def evaluate_pattern(states: list, signals: list[dict],
                     min_signals=1) -> PatternResult:
    """Apply a pattern's rules to one admission's lab state.

    `states` is the list[LabState] the risk score consumes. `signals` are cleaned
    rules ({itemid, name, direction, in_dataset, threshold}). Rules over labs
    this dataset does not carry are reported but never counted — there is nothing
    to measure, and claiming otherwise would overstate the result.
    """
    by_id = {st.itemid: st for st in states}
    outcomes: list[RuleOutcome] = []
    score = 0

    for sig in signals or []:
        itemid = sig.get("itemid")
        direction = sig.get("direction", "")
        testable = bool(sig.get("in_dataset")) and itemid is not None
        threshold = sig.get("threshold")

        if not testable:
            outcomes.append(RuleOutcome(
                itemid=itemid, name=sig.get("name", ""), direction=direction,
                testable=False, threshold=threshold, bound=None, value=None,
                unit="", fired=False, status="normal", trend="stable", points=0))
            continue

        st = by_id.get(itemid)
        bound = rule_bound(itemid, direction, threshold)
        if st is None:
            # the lab exists in this dataset but was never drawn for this patient
            outcomes.append(RuleOutcome(
                itemid=itemid, name=sig.get("name", ""), direction=direction,
                testable=True, threshold=threshold, bound=bound, value=None,
                unit="", fired=False, status="normal", trend="stable", points=0))
            continue

        fired = rule_fires(itemid, st.latest_value, direction, threshold)
        # The pattern's own direction decides what "getting worse" means: a rule
        # for "White Blood Cells LOW" is hunting leukopenia, so a falling white
        # count is the bad news even though the lab dictionary says otherwise.
        tr = trend(itemid, st.series, worsening=direction)
        # Severity stays anchored to the reference range -- how abnormal a value
        # is clinically does not change because a rule set a stricter cut-off.
        # A rule that fired is always worth something though, so a threshold
        # LOOSER than the range cannot match and still score zero.
        sev_pts = max(1, points(itemid, st.latest_value)) if fired else 0
        trend_pts = 1 if (fired and tr == WORSENING) else 0
        total = sev_pts + trend_pts
        score += total

        outcomes.append(RuleOutcome(
            itemid=itemid, name=sig.get("name") or st.test_name, direction=direction,
            testable=True, threshold=threshold, bound=bound,
            value=st.latest_value, unit=st.unit, fired=fired,
            # a rule that did not fire is not evidence, so it is not flagged
            status=classify(itemid, st.latest_value) if fired else "normal",
            trend=tr, points=total))

    n_testable = sum(1 for r in outcomes if r.testable)
    n_fired = sum(1 for r in outcomes if r.fired)
    threshold_n = effective_min_signals(min_signals, n_testable)
    max_score = MAX_POINTS_PER_RULE * n_testable

    return PatternResult(
        rules=outcomes,
        n_testable=n_testable,
        n_fired=n_fired,
        requested_min_signals=int(min_signals or 1),
        min_signals=threshold_n,
        # THE definition of a match. Every caller uses this and only this.
        matched=n_testable > 0 and n_fired >= threshold_n,
        score=score,
        max_score=max_score,
        category=categorize_for_max(score, max_score),
    )
