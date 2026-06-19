"""
M6 EARLY-WARNING ALERTS
=======================
Turn a RiskResult into human-readable, explainable alert messages. Every alert
states WHY it fired -- explainability is the point.
"""
from src.analysis.abnormal import CRITICAL, ABNORMAL
from src.analysis.risk_score import RiskResult, HIGH, MEDIUM
from src.analysis.trends import WORSENING
from src.ingestion.lab_dictionary import LAB_DEFS


def build_alerts(risk: RiskResult) -> list[dict]:
    """Return a list of {level, message} alerts, most severe first."""
    alerts: list[dict] = []

    # overall risk banner
    if risk.category == HIGH:
        alerts.append({"level": "high", "message": f"Patient risk HIGH (score {risk.score})"})
    elif risk.category == MEDIUM:
        alerts.append({"level": "medium", "message": f"Patient risk MEDIUM (score {risk.score})"})

    for c in risk.contributions:
        d = LAB_DEFS[c["itemid"]]
        rng = f"normal {d.low:g}-{d.high:g} {d.unit}"
        val = f"{c['latest_value']:g} {c['unit']}"
        if c["status"] == CRITICAL:
            alerts.append({"level": "high",
                           "message": f"{c['test_name']} = {val} - critically out of range ({rng})"})
        elif c["status"] == ABNORMAL:
            alerts.append({"level": "medium",
                           "message": f"{c['test_name']} = {val} - abnormal ({rng})"})
        if c["trend"] == WORSENING:
            alerts.append({"level": "medium",
                           "message": f"{c['test_name']} worsening over recent measurements"})

    return alerts
