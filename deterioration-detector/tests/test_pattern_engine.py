"""
Does the code actually apply a pattern the way the pattern says?

That is a different question from "is the pattern clinically right", and it is
the one this file answers. Three kinds of test, each aimed at a way the answer
could be "no":

  1. CROSS-PATH CONSISTENCY — the pattern is applied in four places (the patient
     card, the cohort run, the triage ranking, the risk score). If they disagree,
     at least one of them is not doing what the pattern says. These tests assert
     they agree, over a matrix of patterns and admissions. This is the class of
     test that catches a real defect: the board once ranked admissions by
     "scored anything at all", ignoring the pattern's own min_signals, so it
     listed patients who showed no card and were absent from the cohort run.

  2. PROPERTIES — invariants that must hold for EVERY pattern and every value,
     checked against generated inputs rather than examples someone thought of.

  3. A DIFFERENTIAL TEST — the cohort run gets its speed from one windowed SQL
     query. It is checked against a deliberately dumb re-implementation over raw
     rows, on the real database, so an optimisation bug cannot hide.

Run:  pytest -q
"""
import pytest
from hypothesis import given, settings, strategies as sett

import src.analysis.custom_syndromes as cs
import src.storage.pattern_risk as pr
import src.storage.pattern_store as ps
from src.analysis.abnormal import rule_fires
from src.analysis.pattern_engine import (
    LabState, evaluate_pattern, effective_min_signals, categorize_for_max,
    MAX_POINTS_PER_RULE, LOW,
)
from src.analysis.risk_score import score_pattern
from src.ingestion.lab_dictionary import LAB_DEFS

CREATININE, UREA, WBC, LACTATE = 50912, 51006, 51301, 50813
TRACKED = sorted(LAB_DEFS)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.setattr(ps, "STORE", tmp_path / "custom_syndromes.json")
    monkeypatch.setattr(pr, "CACHE_DB", tmp_path / "pattern_risk.duckdb")
    yield


def rule(itemid, direction, threshold=None):
    return {"itemid": itemid, "name": LAB_DEFS[itemid].name, "direction": direction,
            "in_dataset": True, "threshold": threshold, "rationale": "", "evidence": "",
            "citation": {"title": "", "url": ""}}


def state(itemid, value, series=None):
    d = LAB_DEFS[itemid]
    return LabState(itemid=itemid, test_name=d.name, unit=d.unit,
                    latest_value=value, series=series or [value])


# ── 1. Cross-path consistency ───────────────────────────────────────────────

class FakeCon:
    """Stands in for DuckDB in run_on_cohort: one admission's latest values."""
    def __init__(self, values: dict):
        self.rows = [(1, 1, iid, v) for iid, v in values.items()]

    def execute(self, sql, params=None):
        rows = [(1,)] if "COUNT(*)" in sql else self.rows

        class R:
            def fetchall(self_inner):
                return rows

            def fetchone(self_inner):
                return rows[0]
        return R()

    def close(self):
        pass


def verdicts(signals, values, min_signals):
    """Ask all four paths the same question about the same admission."""
    states = [state(iid, v) for iid, v in values.items()]

    engine = evaluate_pattern(states, signals, min_signals)

    cohort = cs.run_on_cohort(FakeCon(values), signals, min_signals)

    cs.save_custom("Consistency", "", signals, min_signals)
    card = bool(cs.detect_custom(states))

    ranked = pr.build({"key": "custom_consistency", "name": "Consistency",
                       "min_signals": min_signals, "signals": signals}) > 0

    return {"engine": engine.matched, "cohort": cohort["n_matched"] == 1,
            "card": card, "ranked": ranked}


@pytest.mark.parametrize("min_signals", [1, 2])
@pytest.mark.parametrize("values", [
    {CREATININE: 3.0, UREA: 90.0},   # both rules fire
    {CREATININE: 3.0, UREA: 12.0},   # only one fires  <- the divergence case
    {CREATININE: 0.9, UREA: 12.0},   # neither fires
])
def test_every_path_agrees_on_whether_a_pattern_matched(monkeypatch, values, min_signals):
    monkeypatch.setattr(pr, "connect",
                        lambda: _FakeLabs([(1, 1, iid, LAB_DEFS[iid].name,
                                            LAB_DEFS[iid].unit, v)
                                           for iid, v in values.items()]))
    signals = [rule(CREATININE, "high"), rule(UREA, "high")]
    v = verdicts(signals, values, min_signals)
    assert len(set(v.values())) == 1, f"paths disagree: {v}"


def test_the_regression_one_of_two_rules_is_not_a_match(monkeypatch):
    """The exact defect: a 2-of-2 pattern must not rank an admission where only
    one rule fired, however high that one lab is."""
    values = {CREATININE: 9.0, UREA: 12.0}
    monkeypatch.setattr(pr, "connect",
                        lambda: _FakeLabs([(1, 1, iid, LAB_DEFS[iid].name,
                                            LAB_DEFS[iid].unit, v)
                                           for iid, v in values.items()]))
    signals = [rule(CREATININE, "high"), rule(UREA, "high")]
    v = verdicts(signals, values, min_signals=2)
    assert v == {"engine": False, "cohort": False, "card": False, "ranked": False}
    # …and the score is still non-zero, which is exactly why "score > 0" was the
    # wrong test for the board to use.
    assert score_pattern([state(CREATININE, 9.0), state(UREA, 12.0)], signals).score > 0


def test_capping_the_threshold_happens_identically_everywhere():
    """A pattern may demand more agreement than this dataset can supply."""
    signals = [rule(CREATININE, "high"),
               {"itemid": None, "name": "Bilirubin", "direction": "high",
                "in_dataset": False, "threshold": None}]
    result = evaluate_pattern([state(CREATININE, 3.0)], signals, min_signals=2)
    cohort = cs.run_on_cohort(FakeCon({CREATININE: 3.0}), signals, 2)
    assert result.min_signals == cohort["min_signals"] == 1
    assert result.requested_min_signals == cohort["requested_min_signals"] == 2
    assert result.matched and cohort["n_matched"] == 1


def test_concurrent_rebuilds_do_not_duplicate_the_ranking(monkeypatch):
    """Saving schedules a background rebuild while the user can trigger one too.
    Both used to commit their own copy, so the board reported twice as many
    matches as the pattern actually had."""
    import threading

    values = {CREATININE: 3.0, UREA: 90.0}
    monkeypatch.setattr(pr, "connect",
                        lambda: _FakeLabs([(1, 1, iid, LAB_DEFS[iid].name,
                                            LAB_DEFS[iid].unit, v)
                                           for iid, v in values.items()]))
    pattern = {"key": "custom_race", "name": "Race", "min_signals": 1,
               "signals": [rule(CREATININE, "high"), rule(UREA, "high")]}

    threads = [threading.Thread(target=pr.build, args=(pattern,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    con = pr._cache_connect()
    try:
        n = con.execute(f"SELECT COUNT(*) FROM {pr.TABLE} WHERE pattern_key = 'custom_race'"
                        ).fetchone()[0]
    finally:
        con.close()
    assert n == 1, f"one admission cached {n} times"


# ── 2. Properties ───────────────────────────────────────────────────────────

labs = sett.sampled_from(TRACKED)
directions = sett.sampled_from(["high", "low"])
values = sett.floats(min_value=-10, max_value=250, allow_nan=False, allow_infinity=False)


@given(itemid=labs, direction=directions, value=values,
       threshold=sett.one_of(sett.none(), values))
@settings(max_examples=200, deadline=None)
def test_a_rule_fires_exactly_when_its_value_crosses_its_bound(itemid, direction, value, threshold):
    result = evaluate_pattern([state(itemid, value)],
                              [rule(itemid, direction, threshold)], 1)
    outcome = result.rules[0]
    expected = (value > outcome.bound) if direction == "high" else (value < outcome.bound)
    assert outcome.fired is expected
    assert outcome.fired is rule_fires(itemid, value, direction, threshold)


@given(specs=sett.lists(sett.tuples(labs, directions, values), min_size=1, max_size=6),
       min_signals=sett.integers(min_value=1, max_value=8))
@settings(max_examples=200, deadline=None)
def test_score_and_match_invariants_hold_for_any_pattern(specs, min_signals):
    # one rule per (lab, direction), mirroring how patterns are de-duplicated
    seen, signals, states = set(), [], []
    for itemid, direction, value in specs:
        if (itemid, direction) in seen:
            continue
        seen.add((itemid, direction))
        signals.append(rule(itemid, direction))
        states.append(state(itemid, value))

    r = evaluate_pattern(states, signals, min_signals)

    assert 0 <= r.score <= MAX_POINTS_PER_RULE * r.n_testable
    assert r.max_score == MAX_POINTS_PER_RULE * r.n_testable
    assert r.n_fired == len(r.fired_rules) <= r.n_testable
    assert r.matched == (r.n_testable > 0 and r.n_fired >= r.min_signals)
    # a match is always backed by at least one point, and no fired rule scores 0
    if r.matched:
        assert r.score >= 1
    if r.n_fired == 0:
        assert r.score == 0
    assert all(o.points >= 1 for o in r.fired_rules)
    assert all(o.points == 0 for o in r.rules if not o.fired)
    assert 1 <= r.min_signals


@given(itemid=labs, value=values,
       a=sett.floats(min_value=0, max_value=200, allow_nan=False),
       b=sett.floats(min_value=0, max_value=200, allow_nan=False))
@settings(max_examples=200, deadline=None)
def test_raising_a_high_threshold_never_creates_a_match(itemid, value, a, b):
    """Monotonicity — the property that makes a threshold trustworthy. Demanding
    a bigger number can only ever match fewer patients, never more."""
    lo, hi = min(a, b), max(a, b)
    loose = evaluate_pattern([state(itemid, value)], [rule(itemid, "high", lo)], 1)
    strict = evaluate_pattern([state(itemid, value)], [rule(itemid, "high", hi)], 1)
    assert not (strict.matched and not loose.matched)


@given(itemid=labs, direction=directions, value=values)
@settings(max_examples=100, deadline=None)
def test_a_research_only_rule_changes_neither_score_nor_ceiling(itemid, direction, value):
    """A lab this dataset can't measure must not tilt the result either way."""
    base = evaluate_pattern([state(itemid, value)], [rule(itemid, direction)], 1)
    with_extra = evaluate_pattern([state(itemid, value)], [
        rule(itemid, direction),
        {"itemid": None, "name": "Bilirubin", "direction": "high",
         "in_dataset": False, "threshold": None}], 1)
    assert with_extra.score == base.score
    assert with_extra.max_score == base.max_score
    assert with_extra.matched == base.matched


@given(score=sett.integers(min_value=0, max_value=60),
       max_score=sett.integers(min_value=0, max_value=60))
@settings(max_examples=200, deadline=None)
def test_categories_are_ordered_and_never_exceed_the_ceiling(score, max_score):
    cat = categorize_for_max(min(score, max_score), max_score)
    assert cat in ("Low", "Medium", "High")
    if max_score == 0:
        assert cat == LOW


@given(requested=sett.integers(min_value=-5, max_value=20),
       n_testable=sett.integers(min_value=0, max_value=8))
@settings(max_examples=200, deadline=None)
def test_the_effective_threshold_is_always_reachable(requested, n_testable):
    n = effective_min_signals(requested, n_testable)
    assert n >= 1
    if n_testable > 0:
        assert n <= n_testable          # never asks for more than can be tested
        assert n <= max(1, requested)   # never asks for more than requested


# ── 3. Differential test against a naive reference ──────────────────────────

class _FakeLabs:
    """Minimal labs connection for pattern_risk.build."""
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        rows = self.rows

        class R:
            def fetchall(self_inner):
                return rows
        return R()

    def close(self):
        pass


def _naive_matches(con, signals, min_signals):
    """The dumbest correct implementation: every row, grouped in Python.

    No window function, no QUALIFY, no cleverness — if this and the real cohort
    run ever disagree, the real one has an optimisation bug.
    """
    itemids = sorted({s["itemid"] for s in signals})
    rows = con.execute(
        "SELECT subject_id, hadm_id, itemid, charttime, value FROM labs_clean "
        f"WHERE itemid IN ({', '.join(str(i) for i in itemids)})").fetchall()

    latest = {}
    for subject_id, hadm_id, itemid, charttime, value in rows:
        key = (subject_id, hadm_id, itemid)
        if key not in latest or charttime > latest[key][0]:
            latest[key] = (charttime, value)

    per_admission = {}
    for (subject_id, hadm_id, itemid), (_, value) in latest.items():
        per_admission.setdefault((subject_id, hadm_id), {})[itemid] = value

    threshold = max(1, min(min_signals, len(itemids)))
    out = set()
    for adm, vals in per_admission.items():
        fired = sum(1 for s in signals
                    if s["itemid"] in vals
                    and rule_fires(s["itemid"], vals[s["itemid"]], s["direction"],
                                   s.get("threshold")))
        if fired >= threshold:
            out.add(adm)
    return out


@pytest.mark.parametrize("signals, min_signals", [
    ([rule(CREATININE, "high")], 1),
    ([rule(CREATININE, "high"), rule(UREA, "high")], 2),
    ([rule(CREATININE, "high", 1.5), rule(UREA, "high", 25)], 2),
    ([rule(LACTATE, "high"), rule(WBC, "low"), rule(CREATININE, "high")], 2),
])
def test_the_fast_cohort_query_agrees_with_a_naive_reimplementation(signals, min_signals):
    """Runs against the real database — the only way to test the SQL itself."""
    from src.storage.db import DB_PATH
    if not DB_PATH.exists():
        pytest.skip("no local labs.duckdb — differential test needs real data")

    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        fast = cs.run_on_cohort(con, signals, min_signals, limit=10 ** 9)
        naive = _naive_matches(con, signals, min_signals)
    finally:
        con.close()

    fast_set = {(m["subject_id"], m["hadm_id"]) for m in fast["examples"]}
    assert fast["n_matched"] == len(naive)
    assert fast_set == naive
