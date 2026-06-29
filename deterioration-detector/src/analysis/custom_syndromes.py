"""
USER-BUILT (CUSTOM) SYNDROMES
=============================
The "Pattern Builder" tab lets a researcher/clinician name a candidate syndrome
and agree, with an AI co-worker that searches the literature, on a set of CITED
pattern rules over the 8 tracked labs. Those saved definitions live here.

Two responsibilities:
  * Persistence — custom syndromes are stored as a small JSON file next to the
    data, NOT in the DuckDB. The DB is opened read-only (and may be the shared
    MotherDuck cloud copy that scripts rebuild), so a side file is the safe,
    durable home for user-authored content.
  * Execution — `run_on_cohort()` applies a custom rule set across every
    admission so the user can immediately see how many real patients match.

A custom syndrome mirrors the built-in `SyndromeDef` shape (name + signals +
min_signals) but each signal additionally carries the rationale and citation the
user agreed on, so the saved definition stays evidence-linked.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.ingestion.lab_dictionary import LAB_DEFS

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data" / "custom_syndromes.json"

HIGH, LOW = "high", "low"
VALID_ITEMIDS = set(LAB_DEFS.keys())


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
    if not STORE.exists():
        return {}
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_store(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_custom() -> list[dict]:
    """All saved custom syndromes, newest first."""
    items = list(_read_store().values())
    items.sort(key=lambda s: s.get("updated", ""), reverse=True)
    return items


def get_custom(key: str) -> dict | None:
    return _read_store().get(key)


def _clean_signals(signals: list[dict]) -> list[dict]:
    """Keep only well-formed signals over the 8 real labs; normalise fields."""
    out, seen = [], set()
    for s in signals or []:
        try:
            itemid = int(s.get("itemid"))
        except (TypeError, ValueError):
            continue
        direction = str(s.get("direction", "")).lower()
        if itemid not in VALID_ITEMIDS or direction not in (HIGH, LOW):
            continue
        dedup = (itemid, direction)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append({
            "itemid": itemid,
            "name": LAB_DEFS[itemid].name,
            "direction": direction,
            "rationale": (s.get("rationale") or "").strip(),
            "evidence": (s.get("evidence") or "").strip(),
            "citation": {
                "title": (s.get("citation", {}) or {}).get("title", "").strip(),
                "url": (s.get("citation", {}) or {}).get("url", "").strip(),
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


# ── Execution against real patient data ──────────────────────────────────────

def _out_of_range(itemid: int, value: float, direction: str) -> bool:
    d = LAB_DEFS[itemid]
    if direction == HIGH:
        return value > d.high
    if direction == LOW:
        return value < d.low
    return False


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
        raise ValueError("No valid rules to run.")
    min_signals = max(1, min(int(min_signals or 1), len(clean)))
    itemids = sorted({s["itemid"] for s in clean})

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

    total_admissions = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT subject_id, hadm_id FROM labs_clean)"
    ).fetchone()[0]

    matches = []
    for (subject_id, hadm_id), vals in latest.items():
        hits = []
        for sig in clean:
            v = vals.get(sig["itemid"])
            if v is not None and _out_of_range(sig["itemid"], v, sig["direction"]):
                hits.append({
                    "itemid": sig["itemid"], "name": sig["name"],
                    "direction": sig["direction"], "value": round(v, 2),
                })
        if len(hits) >= min_signals:
            matches.append({
                "subject_id": subject_id, "hadm_id": hadm_id,
                "n_matched": len(hits), "matched": hits,
            })

    # most signals matched first — the most convincing examples on top
    matches.sort(key=lambda m: m["n_matched"], reverse=True)
    n_matched = len(matches)
    return {
        "n_matched": n_matched,
        "total_admissions": total_admissions,
        "match_rate": round(100 * n_matched / total_admissions, 1) if total_admissions else 0,
        "min_signals": min_signals,
        "n_rules": len(clean),
        "examples": matches[:limit],
    }
