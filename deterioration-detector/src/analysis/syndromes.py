"""
CLINICAL SYNDROME DETECTION
===========================
The risk score (M5) and alerts (M6) treat every lab independently. Real
deterioration, though, usually shows up as a *pattern* across several labs at
once -- e.g. creatinine AND urea rising together points at the kidneys, while
lactate + white cells + falling bicarbonate together suggest sepsis/shock.

This module is a small, transparent rule layer on top of the same per-lab state
the risk score already uses. Each syndrome is a named bundle of "signals"
(this lab, in this direction); a syndrome fires when enough of its signals are
present. Every result is fully explainable: it lists exactly which labs matched
and which expected signals were missing.

Like the rest of src/analysis this is a pure, unit-tested rule engine -- not a
black box and NOT clinical advice.
"""
from dataclasses import dataclass

from src.analysis.abnormal import classify, CRITICAL, NORMAL
from src.analysis.trends import trend, WORSENING
from src.ingestion.lab_dictionary import LAB_DEFS

# Lab itemids (named here so the syndrome table reads clinically).
CREATININE, UREA, POTASSIUM = 50912, 51006, 50971
SODIUM, BICARBONATE, WBC, HEMATOCRIT, LACTATE = 50983, 50882, 51301, 51221, 50813

HIGH, LOW = "high", "low"


@dataclass(frozen=True)
class Signal:
    """One expected lab finding within a syndrome: a lab moving in a direction."""
    itemid: int
    direction: str  # "high" -> above normal range, "low" -> below normal range


@dataclass(frozen=True)
class SyndromeDef:
    key: str
    name: str
    plain: str            # plain-English explanation for a non-clinical reader
    signals: tuple        # tuple[Signal]
    min_signals: int      # how many signals must be present for the syndrome to fire


# Transparent syndrome definitions over the 8 core labs. Direction-specific so
# the same lab can name different syndromes (e.g. high vs low potassium).
SYNDROME_DEFS: list[SyndromeDef] = [
    SyndromeDef(
        "aki", "Acute Kidney Injury",
        "The kidneys appear to be filtering poorly — nitrogen waste products "
        "(creatinine and urea) are building up in the blood together.",
        (Signal(CREATININE, HIGH), Signal(UREA, HIGH)), min_signals=2,
    ),
    SyndromeDef(
        "sepsis", "Possible Sepsis / Shock",
        "A pattern that can mean the body is fighting a serious infection and "
        "tissues are starved of oxygen: rising lactate, abnormal white cells, "
        "and the blood turning acidic.",
        (Signal(LACTATE, HIGH), Signal(WBC, HIGH), Signal(BICARBONATE, LOW)),
        min_signals=2,
    ),
    SyndromeDef(
        "metabolic_acidosis", "Metabolic Acidosis",
        "The blood is turning too acidic (low bicarbonate) while lactate climbs "
        "— often a sign tissues aren't getting enough oxygen.",
        (Signal(BICARBONATE, LOW), Signal(LACTATE, HIGH)), min_signals=2,
    ),
    SyndromeDef(
        "hyperkalemia", "Hyperkalemia (High Potassium)",
        "Potassium is above the safe range, which can disturb the heart's "
        "electrical rhythm.",
        (Signal(POTASSIUM, HIGH),), min_signals=1,
    ),
    SyndromeDef(
        "hypokalemia", "Hypokalemia (Low Potassium)",
        "Potassium has dropped below the safe range, which can cause muscle "
        "weakness and abnormal heart rhythms.",
        (Signal(POTASSIUM, LOW),), min_signals=1,
    ),
    SyndromeDef(
        "dysnatremia", "Sodium Imbalance",
        "Sodium is out of range, disturbing the body's water balance and "
        "affecting the brain and nerves.",
        (Signal(SODIUM, HIGH),), min_signals=1,
    ),
    SyndromeDef(
        "hyponatremia", "Hyponatremia (Low Sodium)",
        "Sodium has fallen below normal, pulling water into cells and "
        "affecting the brain and nerves.",
        (Signal(SODIUM, LOW),), min_signals=1,
    ),
    SyndromeDef(
        "anemia", "Anemia / Possible Blood Loss",
        "The red-cell share of the blood is low, so less oxygen reaches the "
        "tissues — can indicate bleeding.",
        (Signal(HEMATOCRIT, LOW),), min_signals=1,
    ),
]


def _direction(itemid: int, value: float) -> str:
    """Which side of the normal range a value sits on: 'high' | 'low' | 'normal'."""
    d = LAB_DEFS[itemid]
    if value > d.high:
        return HIGH
    if value < d.low:
        return LOW
    return "normal"


def detect_syndromes(states: list) -> list[dict]:
    """
    Match the per-lab state of one admission against the syndrome table.

    `states` is the same list[LabState] the risk score consumes (each has
    itemid, test_name, unit, latest_value, series). Returns the fired syndromes,
    most confident first, each fully explained by its matched/missing signals.
    """
    by_id = {st.itemid: st for st in states}
    results: list[dict] = []

    for syn in SYNDROME_DEFS:
        matched, missing = [], []
        any_critical = False
        any_worsening = False

        for sig in syn.signals:
            st = by_id.get(sig.itemid)
            d = LAB_DEFS[sig.itemid]
            # a signal is present only if the lab exists for this admission and
            # is out of range *in the syndrome's expected direction*.
            if st is not None and _direction(sig.itemid, st.latest_value) == sig.direction:
                status = classify(sig.itemid, st.latest_value)
                tr = trend(sig.itemid, st.series)
                any_critical = any_critical or status == CRITICAL
                any_worsening = any_worsening or tr == WORSENING
                matched.append({
                    "itemid": sig.itemid,
                    "test_name": st.test_name,
                    "unit": st.unit,
                    "value": st.latest_value,
                    "direction": sig.direction,
                    "status": status,
                    "trend": tr,
                })
            else:
                missing.append({"itemid": sig.itemid, "test_name": d.name,
                                "direction": sig.direction})

        if len(matched) < syn.min_signals:
            continue

        # confidence = share of the syndrome's signals that are present.
        confidence = round(100 * len(matched) / len(syn.signals))
        severity = "critical" if any_critical else "warning"
        results.append({
            "key": syn.key,
            "name": syn.name,
            "plain": syn.plain,
            "severity": severity,
            "confidence": confidence,
            "worsening": any_worsening,
            "matched": matched,
            "missing": missing,
        })

    # most confident first, then critical above warning as a tie-breaker
    results.sort(key=lambda r: (r["confidence"], r["severity"] == "critical"),
                 reverse=True)
    return results
