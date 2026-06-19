"""
Lab dictionary (M1 support).

MIMIC-III ships the ITEMID -> test-name mapping in a separate table (D_LABITEMS)
that is NOT included in LABEVENTS. We hardcode the small subset of labs we care
about, together with adult reference ranges and physiologically plausible bounds
used to discard sentinel/garbage values during preprocessing.

Reference ranges are common adult values used for an educational prototype only
(ICU-specific ranges vary); they are NOT clinical advice.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LabDef:
    itemid: int
    name: str
    unit: str
    low: float          # lower bound of normal range
    high: float         # upper bound of normal range
    plausible_min: float  # below this -> treated as garbage/sentinel, dropped
    plausible_max: float  # above this -> treated as garbage, dropped
    # direction that indicates clinical worsening for the trend detector:
    #   "high"  -> rising values are bad (e.g. creatinine)
    #   "low"   -> falling values are bad (e.g. hematocrit)
    #   "both"  -> deviation in either direction is bad (e.g. sodium, potassium)
    worsening: str


# 8 core labs relevant to deterioration / early-warning.
LAB_DEFS = {
    50912: LabDef(50912, "Creatinine",        "mg/dL", 0.6, 1.2,  0.0, 50.0,  "high"),
    51006: LabDef(51006, "Urea Nitrogen",     "mg/dL", 7.0, 20.0, 0.0, 300.0, "high"),
    50971: LabDef(50971, "Potassium",         "mEq/L", 3.5, 5.0,  0.5, 15.0,  "both"),
    50983: LabDef(50983, "Sodium",            "mEq/L", 135, 145,  80,  200,   "both"),
    50882: LabDef(50882, "Bicarbonate",       "mEq/L", 22,  29,   2,   60,    "low"),
    51301: LabDef(51301, "White Blood Cells", "K/uL",  4.0, 11.0, 0.0, 200.0, "high"),
    51221: LabDef(51221, "Hematocrit",        "%",     36,  48,   5,   80,    "low"),
    50813: LabDef(50813, "Lactate",           "mmol/L",0.5, 2.0,  0.0, 40.0,  "high"),
}

CORE_ITEMIDS = sorted(LAB_DEFS.keys())


def name_of(itemid: int) -> str:
    d = LAB_DEFS.get(itemid)
    return d.name if d else str(itemid)
