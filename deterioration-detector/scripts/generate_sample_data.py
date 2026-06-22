"""
SAMPLE DATA GENERATOR
=====================
Writes a synthetic LABEVENTS-shaped CSV that mirrors the real MIMIC-III schema,
so anyone (e.g. a grader) can run the whole project end-to-end WITHOUT the
1.8 GB credentialed MIMIC download.

The file has two parts:

  1. A small CURATED cohort (9 admissions, ids 10001-10009) hand-designed so
     every dashboard panel is populated and the risk engine yields a clean
     3 High / 3 Medium / 3 Low split. These are deterministic and never change.

  2. A large PROCEDURAL cohort (ids 11000+) generated from clinical archetypes
     (worsening / mild / stable / recovering) with realistic per-lab trends and
     noise. We keep appending admissions until the file reaches TARGET_MB, so the
     bundled sample is a substantial, demo-worthy dataset that still sits
     comfortably under GitHub's 100 MB per-file limit.

All numbers are illustrative only and are NOT real patient data.

Run:  python scripts/generate_sample_data.py [target_mb]
Then: python scripts/build_db.py   (auto-detects the sample) and build_risk.py
"""
import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample" / "LABEVENTS_sample.csv"

# Default size target for the generated file. ~90 MB keeps the repo runnable
# out-of-the-box while staying safely under GitHub's 100 MB per-file hard limit.
DEFAULT_TARGET_MB = 90

# itemid -> (test name, unit)  -- must match src/ingestion/lab_dictionary.py
LABS = {
    50912: ("Creatinine", "mg/dL"),
    51006: ("Urea Nitrogen", "mg/dL"),
    50971: ("Potassium", "mEq/L"),
    50983: ("Sodium", "mEq/L"),
    50882: ("Bicarbonate", "mEq/L"),
    51301: ("White Blood Cells", "K/uL"),
    51221: ("Hematocrit", "%"),
    50813: ("Lactate", "mmol/L"),
}
# normal reference ranges (low, high) -- the generic adult ranges our detector
# (src/ingestion/lab_dictionary.py) uses. The series generator targets these.
RANGES = {
    50912: (0.6, 1.2), 51006: (7.0, 20.0), 50971: (3.5, 5.0), 50983: (135, 145),
    50882: (22, 29), 51301: (4.0, 11.0), 51221: (36, 48), 50813: (0.5, 2.0),
}
# "Originating-lab" reference intervals used to set the FLAG column. In real
# MIMIC-III the abnormal flag comes from each analyzer's OWN reference range,
# which differs slightly from the generic adult ranges our detector applies.
# Modelling that small offset here makes the detector-vs-FLAG evaluation
# (scripts/build_risk.py + /api/evaluation) non-trivial instead of a tautology:
# values that fall in the gap between the two range sets become honest
# false-positives / false-negatives near the reference boundaries.
FLAG_RANGES = {
    50912: (0.7, 1.3), 51006: (8.0, 21.0), 50971: (3.5, 5.1), 50983: (136, 145),
    50882: (22, 28), 51301: (4.5, 11.5), 51221: (35, 47), 50813: (0.5, 2.2),
}
# physiologically plausible clamps so generated noise never produces a value
# that build_db.py would discard as garbage (must stay within lab_dictionary).
PLAUSIBLE = {
    50912: (0.1, 45.0), 51006: (2.0, 280.0), 50971: (1.0, 12.0), 50983: (90, 190),
    50882: (4, 55), 51301: (0.5, 180.0), 51221: (8, 75), 50813: (0.2, 35.0),
}

# stable, in-range series for any lab not otherwise specified for an admission
NORMAL = {
    50912: [0.9, 0.9, 1.0, 0.9, 1.0, 0.9],
    51006: [12, 13, 12, 14, 13, 12],
    50971: [4.1, 4.2, 4.0, 4.1, 4.2, 4.1],
    50983: [139, 140, 140, 141, 140, 139],
    50882: [25, 25, 26, 25, 24, 25],
    51301: [6.5, 7.0, 6.8, 7.2, 6.9, 7.0],
    51221: [42, 41, 42, 43, 42, 41],
    50813: [1.0, 1.1, 1.0, 1.2, 1.1, 1.0],
}

# Each curated admission: (subject_id, hadm_id, admit_time, {itemid: series}).
# Any lab omitted from the override dict uses the NORMAL stable series above.
CURATED = [
    # ---------- HIGH risk (3) ----------
    # H1: septic AKI -- almost everything worsening into the critical zone
    (10001, 20001, datetime(2150, 1, 3, 8), {
        50912: [1.0, 1.4, 1.9, 2.4, 3.0, 3.8],
        51006: [16, 24, 36, 48, 62, 80],
        50971: [4.2, 4.6, 5.1, 5.5, 5.9, 6.3],
        50983: [140, 142, 144, 146, 148, 149],
        50882: [24, 22, 20, 17, 14, 11],
        51301: [9, 12, 15, 18, 21, 24],
        51221: [40, 37, 34, 31, 28, 25],
        50813: [1.4, 2.0, 2.8, 3.6, 4.5, 6.0],
    }),
    # H2: metabolic / septic -- a few labs critical, rest stable
    (10002, 20002, datetime(2151, 5, 11, 6), {
        50813: [1.2, 1.8, 2.6, 3.4, 4.2, 5.0],
        50912: [1.0, 1.3, 1.7, 2.1, 2.6, 3.2],
        51301: [8, 10, 13, 16, 18, 20],
        50882: [26, 24, 23, 21, 20, 19],
    }),
    # H3: GI bleed -- hematocrit crashing, urea climbing
    (10003, 20003, datetime(2149, 9, 20, 14), {
        51221: [38, 34, 31, 28, 25, 22],
        51006: [18, 28, 40, 52, 64, 78],
        50912: [1.1, 1.2, 1.3, 1.4, 1.5, 1.6],
    }),

    # ---------- MEDIUM risk (3) ----------
    # M1: early AKI -- mild, rising but not yet critical
    (10004, 20004, datetime(2150, 2, 14, 9), {
        50912: [1.0, 1.1, 1.2, 1.3, 1.4, 1.45],
        51006: [15, 17, 19, 21, 23, 24],
    }),
    # M2: electrolyte disturbance -- a few abnormal but stable values
    (10005, 20005, datetime(2152, 7, 1, 7), {
        50971: [5.1, 5.2, 5.2, 5.3, 5.3, 5.3],
        50983: [133, 132, 132, 133, 132, 132],
        50912: [1.3, 1.3, 1.3, 1.3, 1.3, 1.3],
    }),
    # M3: recovering patient -- started critical, improving (falling trajectory)
    (10006, 20006, datetime(2150, 11, 5, 10), {
        50813: [5.0, 4.2, 3.4, 2.8, 2.5, 2.4],
        50912: [3.0, 2.6, 2.2, 1.8, 1.5, 1.4],
        50882: [16, 18, 19, 20, 21, 21],
        51006: [40, 34, 28, 24, 21, 20],
    }),

    # ---------- LOW risk (3) ----------
    # L1: stable, everything normal
    (10007, 20007, datetime(2151, 3, 18, 8), {}),
    # L2: one borderline-abnormal, otherwise stable
    (10008, 20008, datetime(2150, 6, 22, 12), {
        50983: [134, 134, 133, 134, 134, 134],
    }),
    # L3: normal with mild in-range drift
    (10009, 20009, datetime(2152, 1, 9, 15), {
        50971: [3.4, 3.6, 3.8, 4.0, 4.1, 4.2],
    }),
]

INTERVAL_H = 8  # hours between successive draws (curated cohort)

# Procedural archetypes -> per-lab (start, end) trend over the admission.
# Labs not listed for an archetype track their NORMAL midpoint with mild noise.
# The risk engine scores from the LATEST value (severity) plus the last-3 trend
# (+1 if out-of-range AND worsening), so each archetype's `end` values are chosen
# to land in a target category. Weights reflect a realistic ward mix.
ARCHETYPES = [
    # all labs normal -> score 0 -> Low
    ("low", 0.30, {}),
    # one lab mildly & stably abnormal -> score 1 -> Low
    ("low-borderline", 0.12, {50983: (133, 133)}),
    # two labs rising into the abnormal (not critical) zone -> score ~4 -> Medium
    ("medium", 0.30, {50912: (1.0, 1.4), 51006: (14, 24)}),
    # one lab pushed critical & worsening -> score 3 -> Medium
    ("medium-single", 0.05, {50813: (1.4, 3.6)}),
    # several labs worsening into the critical zone -> score >=6 -> High
    ("high", 0.15, {
        50912: (1.1, 3.0), 51006: (18, 70), 50882: (24, 12),
        51301: (9, 22), 50813: (1.5, 5.0),
    }),
    # started bad, trending back toward normal (improving) -> Low / borderline
    ("recovering", 0.08, {
        50813: (5.2, 2.2), 50912: (3.2, 1.4), 50882: (15, 23), 51006: (44, 19),
    }),
]

# rounding resolution per lab (real LABEVENTS values are coarse): labs whose
# values run >= ~20 are reported as integers, smaller ones to one decimal.
RES = {i: (1.0 if hi >= 20 else 0.1) for i, (_, hi) in RANGES.items()}


def flag_for(itemid: int, value: float) -> str:
    # flagged against the originating-lab interval, NOT our detector's range
    low, high = FLAG_RANGES[itemid]
    return "abnormal" if (value < low or value > high) else ""


def round_val(value: float) -> float:
    """Match the look of real LABEVENTS: integers for larger magnitudes,
    one decimal place for small ones."""
    return round(value) if abs(value) >= 20 else round(value, 1)


def _lab_series(rng: random.Random, itemid: int, start: float, end: float,
                n_points: int) -> list[float]:
    """One lab's series (oldest->newest). The body wanders with light noise; the
    final 3 points form a clean, rounding-safe monotonic step that lands exactly
    on `end`, so severity (latest value) and the worsening trend are both stable
    regardless of series length."""
    pmin, pmax = PLAUSIBLE[itemid]
    width = RANGES[itemid][1] - RANGES[itemid][0]
    dirn = (end > start) - (end < start)          # +1 / 0 / -1
    step = max(1.5 * RES[itemid], 0.12 * width)   # big enough to survive rounding
    delta = dirn * step
    tail = [end - 2 * delta, end - delta, end]    # monotonic toward `end`

    body_n = n_points - len(tail)
    body_target = tail[0]
    body = []
    for i in range(body_n):
        frac = i / (body_n - 1) if body_n > 1 else 0.0
        base = start + (body_target - start) * frac
        base += rng.uniform(-0.025, 0.025) * width
        body.append(base)

    clamp = lambda v: round_val(min(pmax, max(pmin, v)))
    return [clamp(v) for v in body + tail]


def proc_series(rng: random.Random, overrides: dict, n_points: int) -> dict:
    """Build an n-point series for every core lab from an archetype's trends."""
    series = {}
    for itemid in LABS:
        start, end = overrides.get(itemid, (None, None))
        if start is None:
            start = end = sum(RANGES[itemid]) / 2   # stable, in-range
        series[itemid] = _lab_series(rng, itemid, start, end, n_points)
    return series


def write_admission(w, row_state, subj, hadm, t0, series, interval_h):
    n_points = len(next(iter(series.values())))
    n = 0
    for i in range(n_points):
        charttime = (t0 + timedelta(hours=interval_h * i)).strftime("%Y-%m-%d %H:%M:%S")
        for itemid, (name, unit) in LABS.items():
            value = series[itemid][i]
            row_state[0] += 1
            w.writerow([row_state[0], subj, hadm, itemid, charttime,
                        value, value, unit, flag_for(itemid, value)])
            n += 1
    return n


def main() -> None:
    target_mb = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET_MB
    target_bytes = int(target_mb * 1000 * 1000)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2025)  # deterministic output across runs (incl. CI)
    row_state = [0]            # mutable row_id counter shared across admissions
    n_rows = 0
    n_adm = 0
    weights = [w for _, w, _ in ARCHETYPES]

    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        # real MIMIC-III LABEVENTS header
        w.writerow(["ROW_ID", "SUBJECT_ID", "HADM_ID", "ITEMID",
                    "CHARTTIME", "VALUE", "VALUENUM", "VALUEUOM", "FLAG"])

        # --- 1. curated showcase cohort (deterministic 3 High / 3 Medium / 3 Low) ---
        for subj, hadm, t0, overrides in CURATED:
            series = {itemid: overrides.get(itemid, NORMAL[itemid]) for itemid in LABS}
            n_rows += write_admission(w, row_state, subj, hadm, t0, series, INTERVAL_H)
            n_adm += 1

        # --- 2. procedural cohort: grow until the file approaches target_mb ---
        subj = 11000
        base_day = datetime(2150, 1, 1, 7)
        while f.tell() < target_bytes:
            _, _, overrides = rng.choices(ARCHETYPES, weights=weights, k=1)[0]
            n_points = rng.randint(8, 36)        # realistic multi-day ICU stay
            interval_h = rng.choice([6, 8, 12])
            t0 = base_day + timedelta(hours=rng.randint(0, 24 * 365 * 3))
            series = proc_series(rng, overrides, n_points)
            n_rows += write_admission(w, row_state, subj, 21000 + (subj - 11000),
                                      t0, series, interval_h)
            subj += 1
            n_adm += 1
            if n_adm % 500 == 0:
                f.flush()  # keep f.tell() honest against the OS buffer

    size_mb = OUT.stat().st_size / 1e6
    print(f"Wrote {n_rows:,} rows for {n_adm:,} admissions "
          f"({size_mb:.1f} MB, target {target_mb:.0f} MB) -> {OUT}")


if __name__ == "__main__":
    main()
