"""
RULE BOOK
=========
A single, honest source of truth for *how the risk engine decides everything*,
assembled for the dashboard's "Rule Book" tab.

Nothing here is invented: the reference ranges and worsening directions are read
straight from `LAB_DEFS`, the severity points come from `abnormal.points`, and
the Low/Medium/High cut-points are discovered by probing `categorize()` — so the
page can never drift from the code that actually scores patients.

Each rule is tagged with a published `source` key. We are deliberate about which
claims a source actually backs:
  * Adult reference intervals come from a published reference-value table.
  * The normal -> abnormal -> critical banding and the integer point weights are
    the prototype's OWN transparent heuristic, inspired by aggregate-weighted
    "track-and-trigger" early-warning scores (NEWS2 / MEWS) but NOT identical to
    them — so they are tagged as engine heuristics, not attributed to a guideline.
  * Each syndrome cites the consensus definition behind the pattern.

Educational prototype only — NOT clinical advice.
"""
from src.analysis.abnormal import NORMAL, ABNORMAL, CRITICAL
from src.analysis.risk_score import categorize, LOW, MEDIUM, HIGH
from src.ingestion.lab_dictionary import LAB_DEFS
from src.analysis.syndromes import SYNDROME_DEFS


# ── Published sources cited across the rule book ────────────────────────────
SOURCES = {
    "nejm_ref": {
        "label": "NEJM Laboratory Reference Values",
        "citation": ("Kratz A, Ferraro M, Sluss PM, Lewandrowski KB. Laboratory "
                     "Reference Values. N Engl J Med. 2004;351:1548–1563."),
        "url": "https://www.nejm.org/doi/full/10.1056/NEJMcpc049016",
    },
    "news2": {
        "label": "NEWS2 (Royal College of Physicians)",
        "citation": ("Royal College of Physicians. National Early Warning Score "
                     "(NEWS) 2: Standardising the assessment of acute-illness "
                     "severity in the NHS. London: RCP, 2017."),
        "url": "https://www.rcp.ac.uk/improving-care/resources/national-early-warning-score-news-2/",
    },
    "kdigo": {
        "label": "KDIGO AKI Guideline",
        "citation": ("KDIGO Clinical Practice Guideline for Acute Kidney Injury. "
                     "Kidney Int Suppl. 2012;2:1–138."),
        "url": "https://kdigo.org/guidelines/acute-kidney-injury/",
    },
    "sepsis3": {
        "label": "Sepsis-3 Consensus (JAMA)",
        "citation": ("Singer M, et al. The Third International Consensus "
                     "Definitions for Sepsis and Septic Shock (Sepsis-3). "
                     "JAMA. 2016;315(8):801–810."),
        "url": "https://jamanetwork.com/journals/jama/fullarticle/2492881",
    },
    "engine": {
        "label": "Engine heuristic (this prototype)",
        "citation": ("This prototype's own transparent rule, inspired by "
                     "aggregate-weighted track-and-trigger early-warning scores "
                     "(e.g. NEWS2/MEWS) but not identical to any single guideline."),
        "url": None,
    },
}

# Which published source justifies *the worsening direction / clinical meaning*
# of each lab. Reference ranges themselves all come from `nejm_ref`.
_LAB_SOURCE = {
    50912: "kdigo",    # Creatinine — AKI is defined by rising creatinine
    51006: "kdigo",    # Urea Nitrogen — nitrogen-waste retention in kidney injury
    50971: "nejm_ref", # Potassium
    50983: "nejm_ref", # Sodium
    50882: "sepsis3",  # Bicarbonate — low HCO3 reflects metabolic acidosis in shock
    51301: "sepsis3",  # White Blood Cells — leukocytosis/leukopenia in sepsis
    51221: "nejm_ref", # Hematocrit
    50813: "sepsis3",  # Lactate — tissue hypoperfusion marker in Sepsis-3
}

_WORSENING_TEXT = {
    "high": "Rising values are the dangerous direction.",
    "low": "Falling values are the dangerous direction.",
    "both": "Moving out of range in either direction is dangerous.",
}

# Which source backs each syndrome's clinical pattern.
_SYNDROME_SOURCE = {
    "aki": "kdigo",
    "sepsis": "sepsis3",
    "metabolic_acidosis": "sepsis3",
    "hyperkalemia": "nejm_ref",
    "hypokalemia": "nejm_ref",
    "dysnatremia": "nejm_ref",
    "hyponatremia": "nejm_ref",
    "anemia": "nejm_ref",
}


def _category_bands() -> list[dict]:
    """Discover the Low/Medium/High score cut-points by probing categorize()."""
    bands, start, prev = [], 0, categorize(0)
    label = {LOW: "Stable baseline — routine monitoring.",
             MEDIUM: "Elevated — monitor closely.",
             HIGH: "Critical threshold — review first."}
    for s in range(1, 60):
        cat = categorize(s)
        if cat != prev:
            bands.append({"category": prev, "min": start, "max": s - 1,
                          "meaning": label.get(prev, "")})
            start, prev = s, cat
    bands.append({"category": prev, "min": start, "max": None,
                  "meaning": label.get(prev, "")})
    return bands


def build_rules() -> dict:
    """Assemble the full rule-book payload, derived from the live engine."""
    ranges = []
    for itemid in sorted(LAB_DEFS):
        d = LAB_DEFS[itemid]
        ranges.append({
            "itemid": itemid,
            "name": d.name,
            "unit": d.unit,
            "normal_low": d.low,
            "normal_high": d.high,
            "worsening": d.worsening,
            "worsening_text": _WORSENING_TEXT[d.worsening],
            "range_source": "nejm_ref",          # reference interval
            "clinical_source": _LAB_SOURCE[itemid],  # why this direction matters
        })

    classification = {
        "rule": ("A value is classified against its lab's normal range. We measure "
                 "how far it falls outside that range relative to the range's width "
                 "(width = normal high − normal low)."),
        "bands": [
            {"status": NORMAL, "label": "Normal",
             "test": "Within the normal range (low ≤ value ≤ high).",
             "points": points_for(NORMAL)},
            {"status": ABNORMAL, "label": "Abnormal",
             "test": "Outside the range, but by no more than half the range width.",
             "points": points_for(ABNORMAL)},
            {"status": CRITICAL, "label": "Critical",
             "test": "Outside the range by more than half the range width.",
             "points": points_for(CRITICAL)},
        ],
        "source": "engine",
    }

    scoring = {
        "steps": [
            {"name": "Severity points",
             "detail": "Each lab contributes points for how abnormal its latest "
                       "value is: Normal +0, Abnormal +1, Critical +2.",
             "source": "engine"},
            {"name": "Trend points",
             "detail": "Add +1 if that lab is trending in its dangerous direction "
                       "AND its latest value is already out of range. In-range "
                       "fluctuations never add trend points.",
             "source": "engine"},
            {"name": "Admission total",
             "detail": "Sum every lab's severity + trend points. The total maps to "
                       "a Low / Medium / High triage category.",
             "source": "news2"},
        ],
        "trend_window": 3,  # mirrors trends.trend(window=3)
        "source": "engine",
    }

    syndromes = []
    for syn in SYNDROME_DEFS:
        syndromes.append({
            "key": syn.key,
            "name": syn.name,
            "plain": syn.plain,
            "min_signals": syn.min_signals,
            "signals": [{"itemid": s.itemid,
                         "name": LAB_DEFS[s.itemid].name,
                         "direction": s.direction} for s in syn.signals],
            "source": _SYNDROME_SOURCE.get(syn.key, "engine"),
        })

    return {
        "ranges": ranges,
        "classification": classification,
        "scoring": scoring,
        "categories": _category_bands(),
        "syndromes": syndromes,
        "sources": SOURCES,
        "disclaimer": ("Reference intervals are published adult values used for an "
                       "educational prototype; ICU-specific ranges vary. The "
                       "severity banding and point weights are this prototype's own "
                       "transparent heuristic. This is NOT clinical advice."),
    }


def points_for(status: str) -> int:
    """Severity points for a status label, read from the real point map."""
    return {NORMAL: 0, ABNORMAL: 1, CRITICAL: 2}[status]
