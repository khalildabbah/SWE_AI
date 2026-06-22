"""
DETECTOR EVALUATION
===================
How good is our reference-range anomaly detector (M4 `classify`)? MIMIC-III
ships its own `FLAG` column -- the originating lab marked each value "abnormal"
or not -- which we can treat as ground truth and score ourselves against.

We frame it as binary classification:
  * our prediction  = positive  when classify() != normal (value out of range)
  * ground truth    = positive  when FLAG == 'abnormal'

The per-row confusion-matrix counts (tp/fp/fn/tn) are precomputed in DuckDB over
every clean value (see scripts/build_risk.py) and stored in a `flag_eval` table.
This module just turns those counts into the usual metrics -- a pure function so
it can be unit-tested and reused by the API.

NOTE on the bundled SAMPLE: its FLAG is generated from slightly different
("originating-lab") reference ranges than our detector uses, so the comparison
is realistic but illustrative. On real MIMIC-III the divergence reflects genuine
differences between generic adult ranges and each lab's own reference intervals.
"""


def _safe_div(num: int, den: int) -> float:
    return num / den if den else 0.0


def confusion_metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    """Standard binary-classification metrics from confusion-matrix counts."""
    total = tp + fp + fn + tn
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)          # sensitivity
    specificity = _safe_div(tn, tn + fp)
    accuracy = _safe_div(tp + tn, total)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "total": total,
        # rounded to whole-percent so the UI shows clean, honest numbers
        "precision": round(100 * precision, 1),
        "recall": round(100 * recall, 1),
        "specificity": round(100 * specificity, 1),
        "accuracy": round(100 * accuracy, 1),
        "f1": round(100 * f1, 1),
    }
