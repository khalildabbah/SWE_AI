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


def rule_fires(itemid: int, value: float, direction: str,
               threshold: float | None = None) -> bool:
    """Does this value satisfy one pattern rule?

    Without a threshold a rule means "outside the normal reference range on this
    side" — creatinine "high" fires above 1.2 mg/dL. A rule may instead carry the
    threshold its own evidence states (HRS asks for creatinine > 1.5 mg/dL), and
    then that number decides.

    One function so detection, the cohort run and the risk score can never
    disagree about whether a rule fired.
    """
    d = LAB_DEFS[itemid]
    if direction == "high":
        return value > (d.high if threshold is None else threshold)
    if direction == "low":
        return value < (d.low if threshold is None else threshold)
    return False


def rule_bound(itemid: int, direction: str, threshold: float | None = None) -> float:
    """The number a rule actually fires at — what the UI must show the user."""
    d = LAB_DEFS[itemid]
    if threshold is not None:
        return threshold
    return d.high if direction == "high" else d.low
