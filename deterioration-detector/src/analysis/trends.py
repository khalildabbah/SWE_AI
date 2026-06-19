"""
M3 TIME-SERIES TREND ANALYSIS
=============================
Given a time-ordered series of values for one lab, decide whether the patient is
trending toward "worsening", "improving", or "stable" for that lab.

We use two simple, transparent signals:
  1. monotonic run  -> the last `window` values all move in the same direction
  2. linear slope   -> sign of the least-squares slope over the last `window` values
The lab dictionary's `worsening` field defines which direction is clinically bad.
"""
from src.ingestion.lab_dictionary import LAB_DEFS

WORSENING, IMPROVING, STABLE = "worsening", "improving", "stable"


def _slope(values: list[float]) -> float:
    """Least-squares slope of values against their index (0,1,2,...)."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs)
    return num / den if den else 0.0


def trend(itemid: int, values: list[float], window: int = 3) -> str:
    """Classify the recent trend of a single lab's value series (oldest->newest)."""
    if len(values) < window:
        return STABLE
    recent = values[-window:]
    s = _slope(recent)
    if abs(s) < 1e-9:
        return STABLE

    rising = s > 0
    direction = LAB_DEFS[itemid].worsening  # "high" | "low" | "both"
    if direction == "high":
        return WORSENING if rising else IMPROVING
    if direction == "low":
        return WORSENING if not rising else IMPROVING
    # "both": any move away from the midpoint of the normal range is worsening
    d = LAB_DEFS[itemid]
    mid = (d.low + d.high) / 2
    last, first = recent[-1], recent[0]
    moved_away = abs(last - mid) > abs(first - mid)
    return WORSENING if moved_away else IMPROVING
