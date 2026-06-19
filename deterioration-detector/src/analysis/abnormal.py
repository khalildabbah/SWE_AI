"""
M4 ANOMALY DETECTION
====================
Classify a single lab value against its reference range. Pure functions -> easy
to unit-test, no I/O.
"""
from src.ingestion.lab_dictionary import LAB_DEFS

NORMAL, ABNORMAL, CRITICAL = "normal", "abnormal", "critical"


def classify(itemid: int, value: float) -> str:
    """Return 'normal' | 'abnormal' | 'critical' for a value of a given lab."""
    d = LAB_DEFS[itemid]
    if d.low <= value <= d.high:
        return NORMAL
    # distance outside the range, relative to range width
    dist = (d.low - value) if value < d.low else (value - d.high)
    width = d.high - d.low
    return CRITICAL if dist > 0.5 * width else ABNORMAL


def points(itemid: int, value: float) -> int:
    """Severity points used by the risk score: normal=0, abnormal=1, critical=2."""
    return {NORMAL: 0, ABNORMAL: 1, CRITICAL: 2}[classify(itemid, value)]
