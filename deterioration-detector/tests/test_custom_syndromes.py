"""
Tests for the Pattern Builder engine (src/analysis/custom_syndromes):
rule cleaning/validation, JSON persistence, and applying a custom rule set to a
(faked) cohort. Run:  pytest -q
"""
import pytest

import src.analysis.custom_syndromes as cs
import src.storage.pattern_store as ps
from src.analysis.risk_score import LabState

CREATININE = 50912   # normal 0.6-1.2
UREA = 51006         # normal 7-20
POTASSIUM = 50971    # normal 3.5-5.1


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    """Redirect the store to a temp JSON file so tests never touch real data --
    and never reach for MotherDuck, whatever the developer's env happens to have
    set."""
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.setattr(ps, "STORE", tmp_path / "custom_syndromes.json")
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


# ---- lab-name resolution against the full catalog ----
def test_resolve_lab_matches_the_catalog_regardless_of_word_order():
    """"Total Bilirubin" and the catalog's "Bilirubin, Total" are the same test."""
    iid, name, in_ds = cs.resolve_lab(None, "Total Bilirubin")
    assert iid is None and in_ds is False
    assert name == "Bilirubin, Total"   # normalised to the catalog's own name


def test_resolve_lab_keeps_an_unrecognised_name_verbatim():
    iid, name, in_ds = cs.resolve_lab(None, "Vibes Panel")
    assert iid is None and name == "Vibes Panel" and in_ds is False


# ---- persistence backend ----
def test_pattern_store_defaults_to_the_json_file():
    assert ps.backend_name() == "file"
    ps.write_all({"k": {"key": "k", "name": "Kept"}})
    assert ps.read_all()["k"]["name"] == "Kept"


def test_pattern_store_reads_empty_when_the_file_is_corrupt(monkeypatch):
    ps.STORE.parent.mkdir(parents=True, exist_ok=True)
    ps.STORE.write_text("{not json", encoding="utf-8")
    assert ps.read_all() == {}


# ---- detection on one admission (what the monitoring page renders) ----
def _state(itemid, value, series=None, name="Lab", unit="u"):
    return LabState(itemid=itemid, test_name=name, unit=unit,
                    latest_value=value, series=series or [value])


def test_detect_custom_fires_and_matches_the_builtin_card_shape():
    cs.save_custom("Kidney Watch", "Waste products building up.", [
        {"itemid": CREATININE, "direction": "high",
         "citation": {"title": "KDIGO", "url": "https://kdigo.org"}},
        {"itemid": UREA, "direction": "high"},
    ], min_signals=2)

    out = cs.detect_custom([_state(CREATININE, 3.0), _state(UREA, 40.0)])
    assert len(out) == 1
    card = out[0]
    # the same keys detect_syndromes() emits, so one card component renders both
    assert {"key", "name", "plain", "severity", "confidence",
            "worsening", "matched", "missing"} <= card.keys()
    assert card["custom"] is True
    assert card["plain"] == "Waste products building up."
    assert card["confidence"] == 100
    assert card["citations"] == [{"title": "KDIGO", "url": "https://kdigo.org"}]
    assert {m["itemid"] for m in card["matched"]} == {CREATININE, UREA}


def test_detect_custom_stays_silent_below_the_threshold():
    cs.save_custom("Strict", "", [
        {"itemid": CREATININE, "direction": "high"},
        {"itemid": UREA, "direction": "high"},
    ], min_signals=2)
    # only creatinine is out of range, so a 2-of-2 pattern must not fire
    assert cs.detect_custom([_state(CREATININE, 3.0), _state(UREA, 10.0)]) == []


def test_detect_custom_lists_unmatched_rules_as_missing():
    cs.save_custom("Loose", "", [
        {"itemid": CREATININE, "direction": "high"},
        {"itemid": UREA, "direction": "high"},
    ], min_signals=1)
    card = cs.detect_custom([_state(CREATININE, 3.0), _state(UREA, 10.0)])[0]
    assert [m["itemid"] for m in card["matched"]] == [CREATININE]
    assert [m["itemid"] for m in card["missing"]] == [UREA]
    assert card["confidence"] == 50


def test_detect_custom_reports_research_only_rules_separately():
    """A lab the dataset doesn't carry must never count as matched — but the card
    should still say it is part of the pattern."""
    cs.save_custom("Mixed", "", [
        {"itemid": CREATININE, "direction": "high"},
        {"name": "Bilirubin", "direction": "high"},
    ], min_signals=2)
    card = cs.detect_custom([_state(CREATININE, 3.0)])[0]
    assert [r["name"] for r in card["research_only"]] == ["Bilirubin"]
    assert all(m["itemid"] == CREATININE for m in card["matched"])
    assert card["confidence"] == 100  # 1 of 1 testable rule; threshold capped to 1


def test_detect_custom_skips_patterns_with_nothing_testable():
    cs.save_custom("Untestable", "", [{"name": "Bilirubin", "direction": "high"}], 1)
    assert cs.detect_custom([_state(CREATININE, 3.0)]) == []


def test_detect_custom_flags_critical_and_worsening():
    cs.save_custom("Rising", "", [{"itemid": CREATININE, "direction": "high"}], 1)
    card = cs.detect_custom([_state(CREATININE, 6.0, series=[1.0, 3.0, 6.0])])[0]
    assert card["severity"] == "critical"
    assert card["worsening"] is True


def test_detect_custom_writes_a_plain_summary_when_none_was_given():
    cs.save_custom("No Description", "", [{"itemid": POTASSIUM, "direction": "high"}], 1)
    card = cs.detect_custom([_state(POTASSIUM, 7.0)])[0]
    assert "Potassium" in card["plain"] and "above" in card["plain"]


def test_detect_custom_returns_nothing_when_no_patterns_are_saved():
    assert cs.detect_custom([_state(CREATININE, 9.0)]) == []
