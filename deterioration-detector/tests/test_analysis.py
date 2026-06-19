"""
M8 TESTS - unit tests for the analysis engine (anomaly, trend, risk, alerts).
Run:  pytest -q
"""
from src.analysis.abnormal import classify, points, NORMAL, ABNORMAL, CRITICAL
from src.analysis.trends import trend, WORSENING, IMPROVING, STABLE
from src.analysis.risk_score import LabState, score_admission, LOW, HIGH
from src.analysis.alerts import build_alerts

CREATININE = 50912   # normal 0.6-1.2, worsening = high
HEMATOCRIT = 51221   # normal 36-48,  worsening = low
POTASSIUM = 50971    # normal 3.5-5.0, worsening = both


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
