"""
USER-BUILT (CUSTOM) SYNDROMES
=============================
The "Pattern Builder" tab lets a researcher/clinician name a candidate syndrome
and agree, with an AI co-worker that searches the literature, on a set of CITED
pattern rules over the 8 tracked labs. Those saved definitions live here.

Three responsibilities:
  * Persistence — delegated to `src.storage.pattern_store`, which keeps patterns
    in the MotherDuck cloud database when one is configured and in a local JSON
    file otherwise. Either way they live outside the read-only labs DB that the
    build scripts rebuild.
  * Execution — `run_on_cohort()` applies a custom rule set across every
    admission so the user can immediately see how many real patients match.
  * Detection — `detect_custom()` evaluates every saved pattern against ONE
    admission, in the same shape the built-in syndromes use, so user-built
    patterns show up on the patient monitoring page next to the built-in ones.

A custom syndrome mirrors the built-in `SyndromeDef` shape (name + signals +
min_signals) but each signal additionally carries the rationale and citation the
user agreed on, so the saved definition stays evidence-linked.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from src.analysis.abnormal import classify, rule_bound, rule_fires, CRITICAL
from src.analysis.lab_catalog import load_catalog
from src.analysis.trends import trend, WORSENING
from src.ingestion.lab_dictionary import LAB_DEFS
from src.storage import pattern_store

HIGH, LOW = "high", "low"
VALID_ITEMIDS = set(LAB_DEFS.keys())

# Common names/abbreviations for the 8 dataset labs, so a free-text proposal
# like "BUN" or "WBC" still resolves to a runnable (in-dataset) lab.
_LAB_ALIASES = {
    "bun": 51006, "urea": 51006, "urea nitrogen": 51006,
    "wbc": 51301, "white blood cells": 51301, "white blood cell": 51301,
    "white cells": 51301, "leukocytes": 51301, "leucocytes": 51301,
    "creatinine": 50912, "cr": 50912,
    "potassium": 50971, "k": 50971,
    "sodium": 50983, "na": 50983,
    "bicarbonate": 50882, "bicarb": 50882, "hco3": 50882, "co2": 50882,
    "hematocrit": 51221, "haematocrit": 51221, "hct": 51221,
    "lactate": 50813, "lactic acid": 50813,
}


def _norm(name: str) -> str:
    """A word-order- and punctuation-insensitive key for a lab name.

    MIMIC and the literature disagree on how to write the same test:
    "Bilirubin, Total" vs "Total Bilirubin". Lowercasing, dropping punctuation
    and sorting the words folds both into "bilirubin total" so they match.
    """
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return " ".join(sorted(words))


_CATALOG_BY_NORM: dict | None = None


def _catalog_by_norm() -> dict:
    """{normalised name: catalog lab}, built once. Most-measured lab wins a
    collision, since load_catalog() returns them in that order."""
    global _CATALOG_BY_NORM
    if _CATALOG_BY_NORM is None:
        index = {}
        for lab in load_catalog():
            index.setdefault(_norm(lab["label"]), lab)
        _CATALOG_BY_NORM = index
    return _CATALOG_BY_NORM


def resolve_lab(itemid, lab_name: str = "") -> tuple:
    """Map a (itemid, name) pair to (itemid|None, display_name, in_dataset).

    A lab is "in dataset" (runnable on patient data) if it is one of the 8
    tracked labs — matched by itemid, exact name, or a common alias. Anything
    else that we can recognise in the lab catalog comes back under its canonical
    catalog name; anything we can't is kept verbatim. Both are research-only
    patterns with itemid=None.
    """
    if itemid is not None and str(itemid).strip() != "":
        try:
            cand = int(itemid)
        except (TypeError, ValueError):
            cand = None
        if cand in VALID_ITEMIDS:
            return cand, LAB_DEFS[cand].name, True

    key = (lab_name or "").strip()
    if not key:
        return None, "", False

    for iid, d in LAB_DEFS.items():
        if d.name.lower() == key.lower():
            return iid, d.name, True
    alias = _LAB_ALIASES.get(key.lower())
    if alias is not None:
        return alias, LAB_DEFS[alias].name, True

    # Not one of the 8 by name — try the full lab catalog, tolerating word order
    # ("Total Bilirubin" -> "Bilirubin, Total"). A catalog hit that turns out to
    # be tracked after all still becomes a runnable pattern.
    lab = _catalog_by_norm().get(_norm(key))
    if lab is not None:
        if lab["itemid"] in VALID_ITEMIDS:
            return lab["itemid"], LAB_DEFS[lab["itemid"]].name, True
        return None, lab["label"], False

    return None, key, False  # a real lab, just not one we know


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    """A stable, filesystem/url-safe key derived from the syndrome name."""
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return ("custom_" + base) if base else "custom_unnamed"


def available_labs() -> list[dict]:
    """The 8 labs a custom rule can be built from (the only ones in the data)."""
    return [
        {"itemid": d.itemid, "name": d.name, "unit": d.unit,
         "normal_low": d.low, "normal_high": d.high, "worsening": d.worsening}
        for d in LAB_DEFS.values()
    ]


# ── Persistence ────────────────────────────────────────────────────────────

def _read_store() -> dict:
    return pattern_store.read_all()


def _write_store(data: dict) -> None:
    pattern_store.write_all(data)


def list_custom() -> list[dict]:
    """All saved custom syndromes, newest first."""
    items = list(_read_store().values())
    items.sort(key=lambda s: s.get("updated", ""), reverse=True)
    return items


def get_custom(key: str) -> dict | None:
    return _read_store().get(key)


def _clean_threshold(raw) -> float | None:
    """A rule's own firing value, or None to use the lab's reference range.

    Anything unparseable becomes None rather than an error: a rule with a junk
    threshold falls back to the reference range instead of being thrown away.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _clean_signals(signals: list[dict]) -> list[dict]:
    """Normalise pattern rules over ANY lab. Rules over the 8 tracked labs are
    marked in_dataset=True (runnable on patient data); rules over other real
    labs are kept as research-only (itemid=None, in_dataset=False)."""
    out, seen = [], set()
    for s in signals or []:
        direction = str(s.get("direction", "")).lower()
        if direction not in (HIGH, LOW):
            continue
        name_in = s.get("name") or s.get("lab_name") or s.get("lab") or ""
        itemid, name, in_dataset = resolve_lab(s.get("itemid"), name_in)
        if itemid is None and not name:
            continue  # nothing to identify the lab by
        dedup = (itemid if itemid is not None else name.lower(), direction)
        if dedup in seen:
            continue
        seen.add(dedup)
        cite = s.get("citation", {}) or {}
        out.append({
            "itemid": itemid,
            "name": name,
            "direction": direction,
            "in_dataset": in_dataset,
            "threshold": _clean_threshold(s.get("threshold")),
            "rationale": (s.get("rationale") or "").strip(),
            "evidence": (s.get("evidence") or "").strip(),
            "citation": {
                "title": (cite.get("title") or "").strip(),
                "url": (cite.get("url") or "").strip(),
            },
        })
    return out


def save_custom(name: str, description: str, signals: list[dict],
                min_signals: int, key: str | None = None) -> dict:
    """Create or update a custom syndrome. Returns the stored record.

    Raises ValueError on invalid input so the API can return a clean 400.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("A syndrome name is required.")
    clean = _clean_signals(signals)
    if not clean:
        raise ValueError("Add at least one valid pattern rule (lab + direction).")
    try:
        min_signals = int(min_signals)
    except (TypeError, ValueError):
        min_signals = 1
    min_signals = max(1, min(min_signals, len(clean)))

    store = _read_store()
    key = key or _slug(name)
    existing = store.get(key, {})
    record = {
        "key": key,
        "name": name,
        "description": (description or "").strip(),
        "signals": clean,
        "min_signals": min_signals,
        "created": existing.get("created", _now_iso()),
        "updated": _now_iso(),
    }
    store[key] = record
    _write_store(store)
    return record


def delete_custom(key: str) -> bool:
    store = _read_store()
    if key in store:
        del store[key]
        _write_store(store)
        return True
    return False


# ── Detection on a single admission ──────────────────────────────────────────

def _plain_summary(record: dict, signals: list[dict]) -> str:
    """The one-line explanation shown on the pattern card. Prefer what the user
    wrote; otherwise describe the rule set in plain words."""
    described = (record.get("description") or "").strip()
    if described:
        return described
    parts = []
    for s in signals:
        side = "above" if s["direction"] == HIGH else "below"
        if s.get("threshold") is not None:
            parts.append(f"{s['name']} {side} {s['threshold']:g}")
        else:
            parts.append(f"{s['name']} {side} its normal range")
    if len(parts) == 1:
        return f"A user-built pattern: {parts[0]}."
    return ("A user-built pattern, fired when at least "
            f"{record.get('min_signals', 1)} of these are true: " + "; ".join(parts) + ".")


def detect_custom(states: list) -> list[dict]:
    """
    Match every saved custom pattern against the per-lab state of ONE admission.

    Deliberately mirrors `syndromes.detect_syndromes()`: same input (the
    list[LabState] the risk score consumes) and the same output shape, so the
    dashboard renders a user-built pattern with exactly the same card as a
    built-in one. Three extra keys carry what only custom patterns have:
      custom=True, `citations` (the evidence behind the rules) and
      `research_only` (rules over labs this dataset doesn't carry, listed so the
      card is honest about what was actually checked).

    Patterns whose rules are ALL research-only are skipped entirely — there is
    nothing to evaluate, so claiming a result would be misleading.
    """
    by_id = {st.itemid: st for st in states}
    results: list[dict] = []

    for record in list_custom():
        signals = _clean_signals(record.get("signals") or [])
        runnable = [s for s in signals if s["in_dataset"] and s["itemid"] is not None]
        if not runnable:
            continue

        matched, missing = [], []
        any_critical = any_worsening = False
        for sig in runnable:
            st = by_id.get(sig["itemid"])
            if st is not None and _out_of_range(sig["itemid"], st.latest_value,
                                                sig["direction"], sig.get("threshold")):
                status = classify(sig["itemid"], st.latest_value)
                tr = trend(sig["itemid"], st.series)
                any_critical = any_critical or status == CRITICAL
                any_worsening = any_worsening or tr == WORSENING
                matched.append({
                    "itemid": sig["itemid"], "test_name": st.test_name, "unit": st.unit,
                    "value": st.latest_value, "direction": sig["direction"],
                    "status": status, "trend": tr, "threshold": sig.get("threshold"),
                    "bound": rule_bound(sig["itemid"], sig["direction"], sig.get("threshold")),
                    "rationale": sig["rationale"], "citation": sig["citation"],
                })
            else:
                missing.append({"itemid": sig["itemid"], "test_name": sig["name"],
                                "direction": sig["direction"],
                                "threshold": sig.get("threshold"),
                                "bound": rule_bound(sig["itemid"], sig["direction"],
                                                    sig.get("threshold"))})

        # The saved threshold can exceed the number of testable rules; cap it the
        # same way run_on_cohort() does so the pattern stays evaluable.
        min_signals = max(1, min(int(record.get("min_signals") or 1), len(runnable)))
        if len(matched) < min_signals:
            continue

        seen, citations = set(), []
        for s in signals:
            cite = s.get("citation") or {}
            marker = cite.get("url") or cite.get("title")
            if marker and marker not in seen:
                seen.add(marker)
                citations.append({"title": cite.get("title", ""), "url": cite.get("url", "")})

        results.append({
            "key": record.get("key", ""),
            "name": record.get("name", "Custom pattern"),
            "plain": _plain_summary(record, signals),
            "severity": "critical" if any_critical else "warning",
            "confidence": round(100 * len(matched) / len(runnable)),
            "worsening": any_worsening,
            "matched": matched,
            "missing": missing,
            "custom": True,
            "citations": citations,
            "research_only": [
                {"name": s["name"], "direction": s["direction"], "citation": s["citation"]}
                for s in signals if not (s["in_dataset"] and s["itemid"] is not None)
            ],
        })

    results.sort(key=lambda r: (r["confidence"], r["severity"] == "critical"), reverse=True)
    return results


# ── Execution against real patient data ──────────────────────────────────────

def _out_of_range(itemid: int, value: float, direction: str,
                  threshold: float | None = None) -> bool:
    """Thin alias for the shared rule test, kept for readability at call sites."""
    return rule_fires(itemid, value, direction, threshold)


def run_on_cohort(con, signals: list[dict], min_signals: int,
                  limit: int = 50) -> dict:
    """
    Apply a custom rule set to every admission and report who matches.

    A signal is present for an admission when that lab's LATEST value is out of
    range in the signal's direction. An admission matches when at least
    `min_signals` of the rule's signals are present. Efficient: one windowed
    query pulls only the latest value of the relevant labs per admission.
    """
    clean = _clean_signals(signals)
    if not clean:
        raise ValueError("No valid patterns to run.")

    runnable = [s for s in clean if s["in_dataset"] and s["itemid"] is not None]
    skipped = [{"name": s["name"], "direction": s["direction"]}
               for s in clean if not (s["in_dataset"] and s["itemid"] is not None)]
    requested_min = max(1, int(min_signals or 1))

    total_admissions = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT subject_id, hadm_id FROM labs_clean)"
    ).fetchone()[0]

    if not runnable:
        return {
            "n_matched": 0, "total_admissions": total_admissions, "match_rate": 0,
            "min_signals": 0, "requested_min_signals": requested_min,
            "n_rules": len(clean), "n_runnable": 0, "skipped": skipped, "examples": [],
            "note": ("None of these patterns use a lab in this dataset, so the rule "
                     "set can't be tested on patient data yet."),
        }

    # Threshold can't exceed the number of testable patterns.
    effective_min = max(1, min(requested_min, len(runnable)))
    itemids = sorted({s["itemid"] for s in runnable})

    placeholders = ", ".join("?" for _ in itemids)
    rows = con.execute(f"""
        SELECT subject_id, hadm_id, itemid, value
        FROM labs_clean
        WHERE itemid IN ({placeholders})
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY subject_id, hadm_id, itemid ORDER BY charttime DESC) = 1
    """, itemids).fetchall()

    # latest value per (admission, itemid)
    latest: dict[tuple, dict[int, float]] = {}
    for subject_id, hadm_id, itemid, value in rows:
        latest.setdefault((subject_id, hadm_id), {})[itemid] = value

    matches = []
    for (subject_id, hadm_id), vals in latest.items():
        hits = []
        for sig in runnable:
            v = vals.get(sig["itemid"])
            if v is not None and _out_of_range(sig["itemid"], v, sig["direction"],
                                               sig.get("threshold")):
                hits.append({
                    "itemid": sig["itemid"], "name": sig["name"],
                    "direction": sig["direction"], "value": round(v, 2),
                    "bound": rule_bound(sig["itemid"], sig["direction"],
                                        sig.get("threshold")),
                })
        if len(hits) >= effective_min:
            matches.append({
                "subject_id": subject_id, "hadm_id": hadm_id,
                "n_matched": len(hits), "matched": hits,
            })

    # most signals matched first — the most convincing examples on top
    matches.sort(key=lambda m: m["n_matched"], reverse=True)
    n_matched = len(matches)
    note = ""
    if skipped:
        note = (f"{len(skipped)} pattern(s) use a lab not in this dataset and were "
                f"not tested. Matched on the {len(runnable)} testable pattern(s).")
    return {
        "n_matched": n_matched,
        "total_admissions": total_admissions,
        "match_rate": round(100 * n_matched / total_admissions, 1) if total_admissions else 0,
        "min_signals": effective_min,
        "requested_min_signals": requested_min,
        "n_rules": len(clean),
        "n_runnable": len(runnable),
        "skipped": skipped,
        "note": note,
        "examples": matches[:limit],
    }
