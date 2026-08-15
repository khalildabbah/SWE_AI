"""
Tests for scoring an admission by a USER-BUILT pattern rather than the built-in
8-lab risk score (src/analysis/risk_score.score_pattern, the direction override
in trends.trend, and the cached per-pattern cohort ranking).

The point of these: a pattern says which labs matter AND which way they must
move, and the score has to respect both. Run:  pytest -q
"""
import pytest

import src.storage.pattern_risk as pr
import src.storage.pattern_store as ps
from src.analysis.risk_score import (
    LabState, score_pattern, score_admission, categorize_for_max,
    LOW, MEDIUM, HIGH,
)
from src.analysis.trends import trend, WORSENING, IMPROVING

CREATININE = 50912   # normal 0.6-1.2, "worsening" = high
UREA = 51006         # normal 7-20,    "worsening" = high
WBC = 51301          # normal 4-11,    "worsening" = high
BICARB = 50882       # normal 22-29,   "worsening" = low


def st(itemid, value, series=None, name="Lab", unit="u"):
    return LabState(itemid=itemid, test_name=name, unit=unit,
                    latest_value=value, series=series or [value])


def rule(itemid, direction, threshold=None):
    return {"itemid": itemid, "name": "", "direction": direction,
            "in_dataset": True, "threshold": threshold}


# ── a rule's own threshold ───────────────────────────────────────────────────

def test_a_rule_defaults_to_the_reference_range():
    """"High" with no threshold means "above the normal range" — creatinine 1.3
    is over 1.2 and fires."""
    r = score_pattern([st(CREATININE, 1.3)], [rule(CREATININE, "high")])
    assert r.contributions[0]["matched"] is True
    assert r.contributions[0]["bound"] == 1.2


def test_a_stricter_threshold_narrows_what_matches():
    """The case from the HRS pattern: the evidence says creatinine > 1.5, so 1.3
    must NOT match even though it is outside the reference range."""
    r = score_pattern([st(CREATININE, 1.3)], [rule(CREATININE, "high", 1.5)])
    assert r.contributions[0]["matched"] is False
    assert r.contributions[0]["bound"] == 1.5
    assert r.score == 0

    fires = score_pattern([st(CREATININE, 1.6)], [rule(CREATININE, "high", 1.5)])
    assert fires.contributions[0]["matched"] is True


def test_a_looser_threshold_still_scores_at_least_a_point():
    """A threshold inside the normal range means the rule can fire on a value
    classify() calls normal — it must not match and score nothing."""
    r = score_pattern([st(CREATININE, 1.1)], [rule(CREATININE, "high", 1.0)])
    assert r.contributions[0]["matched"] is True
    assert r.contributions[0]["points"] == 1
    assert r.score == 1


def test_severity_stays_anchored_to_the_reference_range():
    """A stricter threshold changes what matches, not how abnormal a value is."""
    r = score_pattern([st(CREATININE, 6.0)], [rule(CREATININE, "high", 1.5)])
    assert r.contributions[0]["status"] == "critical"   # not rescaled to 1.5
    assert r.contributions[0]["points"] == 2


def test_a_low_rule_threshold_fires_below_the_number():
    r = score_pattern([st(WBC, 3.0)], [rule(WBC, "low", 2.0)])
    assert r.contributions[0]["matched"] is False       # 3.0 is not below 2.0
    r = score_pattern([st(WBC, 1.5)], [rule(WBC, "low", 2.0)])
    assert r.contributions[0]["matched"] is True


# ── the direction override on trend() ────────────────────────────────────────

def test_trend_defaults_to_the_lab_dictionary():
    """Unchanged behaviour for every existing caller."""
    assert trend(WBC, [3, 8, 12]) == WORSENING     # rising WBC is bad by default
    assert trend(WBC, [12, 8, 3]) == IMPROVING


def test_trend_direction_can_be_overridden_by_a_pattern():
    """A 'WBC low' rule is hunting leukopenia: a collapsing white count is the
    bad news, and must not be reported as improving."""
    assert trend(WBC, [12, 8, 3], worsening="low") == WORSENING
    assert trend(WBC, [3, 8, 12], worsening="low") == IMPROVING


# ── scaled categories ────────────────────────────────────────────────────────

def test_categories_scale_to_the_patterns_own_ceiling():
    # a 2-rule pattern can score at most 6; the top third is High
    assert [categorize_for_max(s, 6) for s in range(7)] == [
        LOW, LOW, MEDIUM, MEDIUM, HIGH, HIGH, HIGH]


def test_categories_are_low_when_a_pattern_can_score_nothing():
    assert categorize_for_max(0, 0) == LOW


def test_a_small_pattern_can_still_reach_high():
    """With the built-in 0-2/3-5/6+ bands a 2-rule pattern would almost never
    register as High -- the whole reason the bands are scaled."""
    both_critical = score_pattern(
        [st(CREATININE, 6.0), st(UREA, 90.0)],
        [rule(CREATININE, "high"), rule(UREA, "high")])
    assert both_critical.category == HIGH
    assert score_admission([st(CREATININE, 6.0), st(UREA, 90.0)]).score == 4


# ── the point maths ──────────────────────────────────────────────────────────

def test_a_lab_moving_the_wrong_way_scores_nothing():
    """A high white count is not evidence for a pattern that asks for a low one."""
    r = score_pattern([st(WBC, 30.0, [10, 20, 30])], [rule(WBC, "low")])
    assert r.score == 0
    assert r.contributions[0]["matched"] is False
    assert r.contributions[0]["status"] == "normal"  # not evidence, so not flagged


def test_the_trend_bonus_follows_the_rules_direction():
    """The bug this fixes: WBC falling to 2 is worsening for a 'WBC low' rule,
    even though the lab dictionary calls a falling white count an improvement."""
    r = score_pattern([st(WBC, 2.0, [12, 8, 2])], [rule(WBC, "low")])
    assert r.contributions[0]["trend"] == WORSENING
    assert r.contributions[0]["points"] == 2   # 1 severity (abnormal) + 1 trend
    assert r.score == 2


def test_severity_and_trend_add_up_the_same_way_as_the_builtin_score():
    r = score_pattern([st(CREATININE, 6.0, [1.0, 3.0, 6.0])], [rule(CREATININE, "high")])
    # critical (2) + worsening (1) = the 3-point ceiling for one rule
    assert r.score == 3 and r.category == HIGH


def test_a_lab_that_was_never_drawn_is_skipped():
    r = score_pattern([st(CREATININE, 6.0)], [rule(CREATININE, "high"), rule(UREA, "high")])
    assert [c["itemid"] for c in r.contributions] == [CREATININE]
    # the missing lab still counts toward the ceiling, so the score isn't inflated
    assert r.category == MEDIUM   # 2 of a possible 6


def test_research_only_rules_are_ignored():
    """A lab this dataset doesn't carry can't contribute, and must not shrink or
    inflate the ceiling either."""
    signals = [rule(CREATININE, "high"),
               {"itemid": None, "name": "Bilirubin", "direction": "high", "in_dataset": False}]
    r = score_pattern([st(CREATININE, 6.0, [1.0, 3.0, 6.0])], signals)
    assert len(r.contributions) == 1
    assert r.score == 3 and r.category == HIGH  # scored out of 3, not 6


def test_a_pattern_with_no_testable_rule_scores_zero():
    r = score_pattern([st(CREATININE, 6.0)], [
        {"itemid": None, "name": "Bilirubin", "direction": "high", "in_dataset": False}])
    assert r.score == 0 and r.category == LOW and r.contributions == []


def test_contributions_are_sorted_by_impact():
    r = score_pattern(
        [st(CREATININE, 0.9), st(UREA, 90.0, [20, 50, 90])],
        [rule(CREATININE, "high"), rule(UREA, "high")])
    assert r.contributions[0]["itemid"] == UREA      # 3 pts
    assert r.contributions[-1]["points"] == 0        # in range, no evidence


def test_a_low_direction_rule_scores_a_low_value():
    """Bicarbonate is 'worsening = low' in the dictionary, so this agrees with
    the default -- the pattern path must handle it the same way."""
    r = score_pattern([st(BICARB, 8.0, [20, 14, 8])], [rule(BICARB, "low")])
    assert r.contributions[0]["status"] == "critical"
    assert r.score == 3


# ── the cached cohort ranking ────────────────────────────────────────────────

class FakeLabs:
    """Stands in for the labs DB: returns windowed rows for two admissions."""
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        class R:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows
        return R(self.rows)

    def close(self):
        pass


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.setattr(pr, "CACHE_DB", tmp_path / "pattern_risk.duckdb")
    monkeypatch.setattr(ps, "STORE", tmp_path / "custom_syndromes.json")
    yield


def _pattern():
    return {"key": "custom_kidney", "name": "Kidney", "min_signals": 1,
            "signals": [rule(CREATININE, "high"), rule(UREA, "high")]}


def test_build_ranks_and_caches_matching_admissions(temp_cache, monkeypatch):
    rows = [
        # admission (1,1): creatinine climbing into critical, urea high
        (1, 1, CREATININE, "Creatinine", "mg/dL", 1.0),
        (1, 1, CREATININE, "Creatinine", "mg/dL", 3.0),
        (1, 1, CREATININE, "Creatinine", "mg/dL", 6.0),
        (1, 1, UREA, "Urea Nitrogen", "mg/dL", 90.0),
        # admission (2,2): everything in range -> scores nothing, not cached
        (2, 2, CREATININE, "Creatinine", "mg/dL", 0.9),
        (2, 2, UREA, "Urea Nitrogen", "mg/dL", 12.0),
    ]
    monkeypatch.setattr(pr, "connect", lambda: FakeLabs(rows))

    n = pr.build(_pattern())
    assert n == 1                       # only the matching admission is ranked
    assert pr.is_built("custom_kidney") is True

    con = pr._cache_connect()
    try:
        row = con.execute(
            f"SELECT subject_id, hadm_id, score, category, n_matched "
            f"FROM {pr.TABLE} WHERE pattern_key = 'custom_kidney'").fetchone()
    finally:
        con.close()
    assert row[0] == 1 and row[1] == 1
    assert row[2] == 5                  # creatinine 2+1, urea 2+0
    assert row[3] == HIGH
    assert row[4] == 2                  # both rules matched


def test_rebuilding_replaces_the_previous_ranking(temp_cache, monkeypatch):
    rows = [(1, 1, CREATININE, "Creatinine", "mg/dL", 6.0)]
    monkeypatch.setattr(pr, "connect", lambda: FakeLabs(rows))
    pr.build(_pattern())
    pr.build(_pattern())

    con = pr._cache_connect()
    try:
        n = con.execute(
            f"SELECT COUNT(*) FROM {pr.TABLE} WHERE pattern_key = 'custom_kidney'"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 1   # not duplicated


def test_clear_removes_a_cached_ranking(temp_cache, monkeypatch):
    monkeypatch.setattr(pr, "connect",
                        lambda: FakeLabs([(1, 1, CREATININE, "Creatinine", "mg/dL", 6.0)]))
    pr.build(_pattern())
    pr.clear("custom_kidney")
    assert pr.is_built("custom_kidney") is False


def test_build_refuses_a_pattern_with_nothing_testable(temp_cache):
    n = pr.build({"key": "custom_x", "name": "X", "signals": [
        {"itemid": None, "name": "Bilirubin", "direction": "high", "in_dataset": False}]})
    assert n == 0


def test_is_built_is_false_before_anything_is_cached(temp_cache):
    assert pr.is_built("custom_never") is False
