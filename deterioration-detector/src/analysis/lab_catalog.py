"""
LAB CATALOG
===========
The full set of named labs present in the source LABEVENTS extract, joined to
MIMIC's D_LABITEMS dictionary and exported to data/lab_catalog.csv. This powers
the Pattern Builder's lab pick-list so researchers choose from real labs by name
and category instead of typing free text.

Each lab is flagged `testable` when the system actually tracks it (i.e. it has a
reference range in lab_dictionary.LAB_DEFS, so it can be run on patient data).
Everything else is selectable too, but saved as a research-only pattern.

The CSV is a small, committed artifact (≈700 rows) so the endpoint works in
deploy without the multi-GB raw files. Regenerate it with scripts/build_db's
sibling tooling if the source extract changes.
"""
from __future__ import annotations

import csv
from pathlib import Path

from src.ingestion.lab_dictionary import LAB_DEFS

ROOT = Path(__file__).resolve().parents[2]
CATALOG_CSV = ROOT / "data" / "lab_catalog.csv"

_CACHE: list[dict] | None = None


def _first_unit(units: str) -> str:
    """The catalog stores ';'-joined unit variants; take the first real one."""
    for u in (units or "").split(";"):
        u = u.strip()
        if u:
            return u
    return ""


def load_catalog() -> list[dict]:
    """All named labs from the export, most-measured first. Cached in-process."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    out: list[dict] = []
    if CATALOG_CSV.exists():
        with open(CATALOG_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    itemid = int(r["itemid"])
                except (TypeError, ValueError, KeyError):
                    continue
                label = (r.get("label") or "").strip()
                if not label:
                    continue
                try:
                    n_rows = int(r.get("n_rows") or 0)
                except ValueError:
                    n_rows = 0
                tracked = LAB_DEFS.get(itemid)
                out.append({
                    "itemid": itemid,
                    "label": label,
                    # Title-case folds MIMIC's case-variant categories
                    # ("CHEMISTRY" vs "Chemistry") into one bucket.
                    "category": (r.get("category") or "").strip().title(),
                    "fluid": (r.get("fluid") or "").strip(),
                    # Prefer the tracked lab's own unit — it is the unit every
                    # threshold and reference range in the app is expressed in.
                    "units": tracked.unit if tracked else _first_unit(r.get("units")),
                    "n_rows": n_rows,
                    "testable": tracked is not None,
                    # Present only for tracked labs: what "high"/"low" mean by
                    # default, so the builder can show the number a rule fires at.
                    "normal_low": tracked.low if tracked else None,
                    "normal_high": tracked.high if tracked else None,
                })

    out.sort(key=lambda x: x["n_rows"], reverse=True)
    _CACHE = out
    return out
