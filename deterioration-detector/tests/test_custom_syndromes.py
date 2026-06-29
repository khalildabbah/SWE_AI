"""
Tests for the Pattern Builder engine (src/analysis/custom_syndromes):
rule cleaning/validation, JSON persistence, and applying a custom rule set to a
(faked) cohort. Run:  pytest -q
"""
import pathlib

import pytest

import src.analysis.custom_syndromes as cs

CREATININE = 50912   # normal 0.6-1.2
UREA = 51006         # normal 7-20


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    """Redirect the JSON store to a temp file so tests never touch real data."""
    monkeypatch.setattr(cs, "STORE", tmp_path / "custom_syndromes.json")
    yield


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


class FakeCon:
    """Minimal DuckDB stand-in: returns the latest-value rows for the windowed
    query and a total-admissions count for the COUNT(*) query."""
    def __init__(self, rows, total):
        self.rows, self.total = rows, total

    def execute(self, sql, params=None):
        if "COUNT(*)" in sql:
            return FakeResult([(self.total,)])
        return FakeResult(self.rows)


# ---- labs ----
def test_available_labs_are_the_eight():
    labs = cs.available_labs()
    assert len(labs) == 8
    assert {"itemid", "name", "unit", "normal_low", "normal_high", "worsening"} <= labs[0].keys()


# ---- save / validate ----
def test_save_drops_invalid_and_duplicate_signals():
    rec = cs.save_custom("Test AKI", "kidney", [
        {"itemid": CREATININE, "direction": "high", "rationale": "rises",
         "citation": {"title": "KDIGO", "url": "http://x"}},
        {"itemid": UREA, "direction": "high"},
        {"itemid": 99999, "direction": "high"},        # not one of the 8 -> dropped
        {"itemid": CREATININE, "direction": "high"},    # duplicate -> dropped
        {"itemid": CREATININE, "direction": "sideways"},  # bad direction -> dropped
    ], min_signals=2)
    assert len(rec["signals"]) == 2
    assert rec["signals"][0]["name"] == "Creatinine"
    assert rec["min_signals"] == 2


def test_min_signals_clamped_to_rule_count():
    rec = cs.save_custom("X", "", [{"itemid": CREATININE, "direction": "high"}], min_signals=9)
    assert rec["min_signals"] == 1


def test_save_requires_name_and_valid_signal():
    with pytest.raises(ValueError):
        cs.save_custom("", "", [{"itemid": CREATININE, "direction": "high"}], 1)
    with pytest.raises(ValueError):
        cs.save_custom("Name", "", [{"itemid": 1, "direction": "high"}], 1)


def test_save_list_and_delete_roundtrip():
    rec = cs.save_custom("Round Trip", "", [{"itemid": UREA, "direction": "high"}], 1)
    assert [s["key"] for s in cs.list_custom()] == [rec["key"]]
    assert cs.delete_custom(rec["key"]) is True
    assert cs.list_custom() == []
    assert cs.delete_custom(rec["key"]) is False


# ---- run on cohort ----
def _signals():
    return [
        {"itemid": CREATININE, "direction": "high"},
        {"itemid": UREA, "direction": "high"},
    ]


def test_run_matches_when_min_signals_met():
    # adm (1,1): both high -> 2 matches; adm (2,2): only creatinine high -> 1 match
    rows = [
        (1, 1, CREATININE, 2.0), (1, 1, UREA, 30.0),
        (2, 2, CREATININE, 2.5), (2, 2, UREA, 10.0),
    ]
    out = cs.run_on_cohort(FakeCon(rows, total=2), _signals(), min_signals=2)
    assert out["n_matched"] == 1
    assert out["total_admissions"] == 2
    assert out["match_rate"] == 50.0
    assert out["examples"][0]["subject_id"] == 1


def test_run_min_one_matches_more():
    rows = [
        (1, 1, CREATININE, 2.0), (1, 1, UREA, 30.0),
        (2, 2, CREATININE, 2.5), (2, 2, UREA, 10.0),
    ]
    out = cs.run_on_cohort(FakeCon(rows, total=2), _signals(), min_signals=1)
    assert out["n_matched"] == 2
    # most-matched admission sorts first
    assert out["examples"][0]["n_matched"] == 2


def test_run_rejects_empty_rules():
    with pytest.raises(ValueError):
        cs.run_on_cohort(FakeCon([], total=0), [], min_signals=1)


# ---- beyond the 8 labs (research-only) ----
def test_resolve_lab_dataset_alias_and_unknown():
    iid, name, in_ds = cs.resolve_lab(None, "BUN")
    assert iid == UREA and in_ds is True
    iid, name, in_ds = cs.resolve_lab(None, "Bilirubin")
    assert iid is None and name == "Bilirubin" and in_ds is False


def test_save_keeps_research_only_lab():
    rec = cs.save_custom("Liver-ish", "", [
        {"itemid": CREATININE, "direction": "high"},
        {"name": "Bilirubin", "direction": "high",
         "citation": {"title": "Some review", "url": "http://b"}},
    ], min_signals=2)
    by_name = {s["name"]: s for s in rec["signals"]}
    assert by_name["Creatinine"]["in_dataset"] is True
    assert by_name["Bilirubin"]["in_dataset"] is False
    assert by_name["Bilirubin"]["itemid"] is None


def test_run_skips_non_dataset_labs():
    rows = [(1, 1, CREATININE, 2.0)]  # only creatinine is in the data
    signals = [
        {"itemid": CREATININE, "direction": "high"},
        {"name": "Bilirubin", "direction": "high"},  # research-only -> skipped
    ]
    out = cs.run_on_cohort(FakeCon(rows, total=1), signals, min_signals=2)
    assert out["n_runnable"] == 1
    assert len(out["skipped"]) == 1 and out["skipped"][0]["name"] == "Bilirubin"
    assert out["min_signals"] == 1            # capped from requested 2 to 1 runnable
    assert out["requested_min_signals"] == 2
    assert out["n_matched"] == 1              # creatinine high fires


def test_run_all_research_only_matches_nothing():
    signals = [{"name": "Bilirubin", "direction": "high"}]
    out = cs.run_on_cohort(FakeCon([], total=5), signals, min_signals=1)
    assert out["n_runnable"] == 0 and out["n_matched"] == 0
    assert "can't be tested on patient data" in out["note"]
