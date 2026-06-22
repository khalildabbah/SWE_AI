"""
M8 TESTS - unit tests for the analysis engine (anomaly, trend, risk, alerts).
Run:  pytest -q
"""
from src.analysis.abnormal import classify, points, NORMAL, ABNORMAL, CRITICAL
from src.analysis.trends import trend, WORSENING, IMPROVING, STABLE
from src.analysis.risk_score import LabState, score_admission, LOW, HIGH
from src.analysis.alerts import build_alerts
from src.analysis.syndromes import detect_syndromes
from src.analysis.evaluation import confusion_metrics
from src.analysis.lead_time import compute_lead_time
from datetime import datetime, timedelta

CREATININE = 50912   # normal 0.6-1.2, worsening = high
HEMATOCRIT = 51221   # normal 36-48,  worsening = low
POTASSIUM = 50971    # normal 3.5-5.0, worsening = both
UREA = 51006         # normal 7-20,   worsening = high
BICARBONATE = 50882  # normal 22-29,  worsening = low
WBC = 51301          # normal 4-11,   worsening = high
LACTATE = 50813      # normal 0.5-2.0, worsening = high
SODIUM = 50983       # normal 135-145


# ---- M4 anomaly ----
def test_classify_normal_abnormal_critical():
    assert classify(CREATININE, 1.0) == NORMAL
    assert classify(CREATININE, 1.4) == ABNORMAL      # just over high
    assert classify(CREATININE, 3.0) == CRITICAL      # far over high

def test_points_mapping():
    assert points(CREATININE, 1.0) == 0
    assert points(CREATININE, 1.4) == 1
    assert points(CREATININE, 3.0) == 2


# ---- M3 trend ----
def test_trend_rising_creatinine_is_worsening():
    assert trend(CREATININE, [1.0, 1.5, 2.2]) == WORSENING

def test_trend_falling_hematocrit_is_worsening():
    assert trend(HEMATOCRIT, [40, 33, 28]) == WORSENING

def test_trend_needs_enough_points():
    assert trend(CREATININE, [1.0, 2.0]) == STABLE     # < window

def test_trend_improving():
    assert trend(CREATININE, [3.0, 2.0, 1.0]) == IMPROVING


# ---- M5 risk score ----
def test_healthy_patient_is_low_risk():
    states = [LabState(CREATININE, "Creatinine", "mg/dL", 1.0, [0.9, 1.0, 1.0])]
    r = score_admission(states)
    assert r.category == LOW and r.score == 0

def test_sick_patient_is_high_risk():
    states = [
        LabState(CREATININE, "Creatinine", "mg/dL", 3.0, [1.2, 2.0, 3.0]),   # critical+worsening = 3
        LabState(HEMATOCRIT, "Hematocrit", "%", 25, [38, 30, 25]),           # critical+worsening = 3
        LabState(POTASSIUM, "Potassium", "mEq/L", 6.5, [5.2, 6.0, 6.5]),     # critical+worsening = 3
    ]
    r = score_admission(states)
    assert r.category == HIGH and r.score >= 6

def test_contributions_sorted_by_points():
    states = [
        LabState(CREATININE, "Creatinine", "mg/dL", 1.0, [1.0, 1.0, 1.0]),   # 0 pts
        LabState(HEMATOCRIT, "Hematocrit", "%", 25, [38, 30, 25]),           # 3 pts
    ]
    r = score_admission(states)
    assert r.contributions[0]["test_name"] == "Hematocrit"


# ---- M6 alerts ----
def test_alerts_fire_for_critical_value():
    states = [LabState(CREATININE, "Creatinine", "mg/dL", 3.0, [1.2, 2.0, 3.0])]
    alerts = build_alerts(score_admission(states))
    msgs = " ".join(a["message"] for a in alerts)
    assert "Creatinine" in msgs and "critically" in msgs
    assert any(a["level"] == "high" for a in alerts)


# ---- clinical syndrome detection ----
def _state(itemid, name, unit, latest, series):
    return LabState(itemid, name, unit, latest, series)


def test_aki_fires_when_creatinine_and_urea_both_high():
    states = [
        _state(CREATININE, "Creatinine", "mg/dL", 2.5, [1.2, 1.8, 2.5]),
        _state(UREA, "Urea Nitrogen", "mg/dL", 40, [22, 30, 40]),
    ]
    syns = {s["key"]: s for s in detect_syndromes(states)}
    assert "aki" in syns
    assert syns["aki"]["confidence"] == 100        # both signals present
    assert syns["aki"]["severity"] == "critical"   # creatinine 2.5 is critical
    assert syns["aki"]["worsening"] is True


def test_aki_does_not_fire_on_single_lab():
    # only creatinine high; urea normal -> 1 of 2 signals, below min_signals
    states = [
        _state(CREATININE, "Creatinine", "mg/dL", 2.5, [1.2, 1.8, 2.5]),
        _state(UREA, "Urea Nitrogen", "mg/dL", 12, [11, 12, 12]),
    ]
    assert "aki" not in {s["key"] for s in detect_syndromes(states)}


def test_sepsis_fires_on_two_of_three_signals():
    states = [
        _state(LACTATE, "Lactate", "mmol/L", 4.0, [1.0, 2.5, 4.0]),
        _state(WBC, "White Blood Cells", "K/uL", 18, [9, 14, 18]),
        _state(BICARBONATE, "Bicarbonate", "mEq/L", 25, [25, 25, 25]),  # normal
    ]
    syns = {s["key"]: s for s in detect_syndromes(states)}
    assert "sepsis" in syns
    assert syns["sepsis"]["confidence"] == 67       # 2 of 3 signals
    assert len(syns["sepsis"]["missing"]) == 1      # bicarbonate not matched


def test_direction_specific_potassium_syndromes():
    high_k = detect_syndromes([_state(POTASSIUM, "Potassium", "mEq/L", 6.2, [5.1, 5.8, 6.2])])
    low_k = detect_syndromes([_state(POTASSIUM, "Potassium", "mEq/L", 2.8, [3.6, 3.2, 2.8])])
    assert "hyperkalemia" in {s["key"] for s in high_k}
    assert "hypokalemia" in {s["key"] for s in low_k}


def test_no_syndromes_when_all_normal():
    states = [
        _state(CREATININE, "Creatinine", "mg/dL", 1.0, [1.0, 1.0, 1.0]),
        _state(SODIUM, "Sodium", "mEq/L", 140, [140, 140, 140]),
    ]
    assert detect_syndromes(states) == []


# ---- detector evaluation (confusion-matrix metrics) ----
def test_confusion_metrics_basic():
    m = confusion_metrics(tp=90, fp=10, fn=30, tn=870)
    assert m["total"] == 1000
    assert m["accuracy"] == 96.0
    assert m["precision"] == 90.0          # 90/(90+10)
    assert m["recall"] == 75.0             # 90/(90+30)
    assert m["specificity"] == 98.9        # 870/(870+10) -> 98.86 rounded

def test_confusion_metrics_no_division_by_zero():
    m = confusion_metrics(tp=0, fp=0, fn=0, tn=0)
    assert m["precision"] == 0.0 and m["recall"] == 0.0 and m["f1"] == 0.0


# ---- early-warning lead time ----
def _series(points_by_lab):
    """Build the {itemid: {...,"points":[(charttime,value)]}} shape from hour offsets."""
    base = datetime(2026, 1, 1, 0, 0, 0)
    return {
        itemid: {"test_name": name, "unit": unit,
                 "points": [(base + timedelta(hours=h), v) for (h, v) in pts]}
        for itemid, (name, unit, pts) in points_by_lab.items()
    }


def test_lead_time_warns_before_first_critical():
    # three labs drift abnormal+worsening (score hits High at hour 8) while every
    # value is still only "abnormal"; creatinine goes critical later at hour 12.
    s = _series({
        CREATININE: ("Creatinine", "mg/dL", [(0, 1.3), (3, 1.4), (6, 1.45), (12, 2.0)]),
        UREA: ("Urea Nitrogen", "mg/dL", [(1, 22), (4, 24), (7, 25)]),
        WBC: ("White Blood Cells", "K/uL", [(2, 12), (5, 13), (8, 14)]),
    })
    r = compute_lead_time(s)
    assert r.concerned and r.alerted and r.deteriorated
    assert r.event_lab == "Creatinine" and r.event_hours == 12.0
    assert r.alert_hours == 8.0                       # High first reached here
    assert r.concern_hours <= r.alert_hours           # concern (Medium+) no later
    assert r.lead_alert_hours == 4.0                  # 12 - 8 hours of warning
    assert r.lead_concern_hours >= r.lead_alert_hours  # concern warns at least as early
    assert r.alert_time is not None and r.event_time is not None


def test_lead_time_deteriorated_but_never_alerted_high():
    # one lab goes critical: that's enough for Medium (concern) but not High (alert)
    s = _series({CREATININE: ("Creatinine", "mg/dL", [(0, 1.0), (1, 1.1), (2, 3.0)])})
    r = compute_lead_time(s)
    assert r.deteriorated and not r.alerted
    assert r.event_lab == "Creatinine" and r.event_hours == 2.0
    assert r.lead_alert_hours is None                 # never reached High
    assert r.concerned and r.lead_concern_hours == 0.0  # Medium coincides with event


def test_lead_time_none_when_all_normal():
    s = _series({
        CREATININE: ("Creatinine", "mg/dL", [(0, 1.0), (1, 1.0), (2, 1.0)]),
        SODIUM: ("Sodium", "mEq/L", [(0, 140), (1, 140), (2, 140)]),
    })
    r = compute_lead_time(s)
    assert not r.concerned and not r.alerted and not r.deteriorated
    assert r.lead_concern_hours is None and r.event_lab is None


def test_lead_time_empty_series():
    r = compute_lead_time({})
    assert not r.concerned and not r.alerted and not r.deteriorated
    assert r.lead_concern_hours is None and r.lead_alert_hours is None
