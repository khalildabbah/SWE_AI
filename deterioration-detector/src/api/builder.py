"""
PATTERN BUILDER API
===================
Backs the "Pattern Builder" tab, where a researcher names a candidate syndrome
and co-works with an AI to agree on CITED pattern rules over the 8 tracked labs,
then tries the rule set on real patient data.

Endpoints (all under /api/builder):
  GET    /labs              -> the 8 labs a rule can be built from
  GET    /catalog           -> every named lab, for the pick-list
  GET    /syndromes         -> saved custom syndromes
  POST   /syndromes         -> create / update a custom syndrome
  DELETE /syndromes/{key}   -> delete one
  GET    /export            -> every saved syndrome as a portable JSON payload
  POST   /import            -> merge an exported payload back in
  POST   /research          -> co-work turn: live web search -> reply + cited
                               rule proposals (OpenAI Responses API)
  POST   /run               -> apply a rule set across the cohort, report matches

The research turn uses OpenAI's hosted `web_search` tool so the citations are
real, fetched links rather than the model's recollection. The API key is read
from OPENAI_API_KEY and never leaves the server.
"""
from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.storage.db import connect
from src.storage import pattern_risk
from src.analysis.custom_syndromes import (
    available_labs, list_custom, get_custom, save_custom, delete_custom,
    run_on_cohort, resolve_lab,
)
from src.analysis.lab_catalog import load_catalog
from src.ingestion.lab_dictionary import LAB_DEFS
from src.storage import pattern_store

router = APIRouter(prefix="/api/builder")

# Web search is supported on the 4o / 4.1 families via the Responses API.
BUILDER_MODEL = os.getenv("OPENAI_BUILDER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o"))

_LAB_LINES = "\n".join(
    f"  - {d.name} (itemid {d.itemid}, {d.unit}; normal {d.low}-{d.high}; "
    f"clinically worse when {d.worsening})"
    for d in LAB_DEFS.values()
)

SYSTEM_PROMPT = f"""\
You are a clinical-research co-pilot inside the "Pattern Builder" of an
educational patient-deterioration prototype. The user is naming a candidate
syndrome and wants to agree with you on a small set of evidence-based PATTERN
RULES that, taken together, suggest that syndrome from blood-lab values.

You may propose patterns over ANY blood lab that the evidence supports — you are
NOT limited to a fixed list. Be guided by the literature for the syndrome.

One thing to be transparent about: this prototype's patient dataset currently
contains only these 8 labs, so only patterns over them can be TESTED on patient
data right now. Patterns over any other lab are still valuable and are saved as
"research-only":
{_LAB_LINES}

Each pattern rule is exactly: ONE lab, moving in ONE direction
("high" = above normal range, "low" = below normal range), with a short plain
rationale, an inline evidence synopsis, and a real citation.

HOW TO WORK:
- Use the web_search tool to ground every proposal in actual literature
  (guidelines, review articles, primary studies). Prefer authoritative sources
  (e.g. KDIGO, Sepsis-3, NEWS2, major journals). Cite what you actually found.
- BRING THE EVIDENCE INTO THE CHAT. The user should be able to read, understand
  and decide WITHOUT leaving this page to open the links. For every source you
  rely on, give a concise synopsis in your prose (2-4 sentences of what it
  actually says, with a short quoted finding when it helps), and put that same
  synopsis in each proposal's "evidence" field. The citation/link is for
  provenance only — never make the user click out to follow your reasoning.
- Discuss with the user in clear, concise prose. When you propose or revise
  rules, ALSO emit a fenced ```json block (and nothing else inside the fences)
  with this exact shape:
  {{"proposals": [
     {{"lab": "<lab name>", "itemid": <real itemid if it is one of the 8 above,
       else null>, "direction": "high"|"low", "rationale": "<one sentence, plain>",
       "evidence": "<2-4 sentence synopsis of what the source says, so the user
                     can decide here without opening the link>",
       "citation": {{"title": "<source title>", "url": "<real url>"}}}}
  ]}}
- ALWAYS set "lab" to the lab's name. Set "itemid" to the matching id ONLY when
  the lab is one of the 8 above; otherwise use null (it becomes a research-only
  pattern). Do propose important non-dataset labs (e.g. bilirubin, glucose,
  platelets) when the evidence calls for them — just leave their itemid null.
- Keep proposals focused (typically 2-5 rules). Do not invent citations; if you
  could not find a source, say so and omit that rule from the JSON.
- This is an educational tool, not medical advice. Never give diagnosis or
  treatment guidance for an individual.
"""


class ResearchTurn(BaseModel):
    role: str   # "user" | "model"
    text: str


class ResearchRequest(BaseModel):
    name: str = ""
    description: str = ""
    message: str
    history: list[ResearchTurn] = []


class SignalIn(BaseModel):
    itemid: int | None = None   # None for research-only labs not in the dataset
    name: str = ""
    direction: str
    rationale: str = ""
    evidence: str = ""
    citation: dict = {}


class SyndromeIn(BaseModel):
    name: str
    description: str = ""
    signals: list[SignalIn] = []
    min_signals: int = 1
    key: str | None = None


class RunRequest(BaseModel):
    signals: list[SignalIn] = []
    min_signals: int = 1


class ImportRequest(BaseModel):
    items: list[SyndromeIn] = []


# ── Labs + CRUD ──────────────────────────────────────────────────────────────

@router.get("/labs")
def labs():
    """The 8 labs that are testable on patient data (have reference ranges)."""
    return {"labs": available_labs()}


@router.get("/catalog")
def catalog():
    """Every named lab in the source extract — the Pattern Builder pick-list.
    `testable=true` means the system tracks it and it can be run on patient data;
    the rest are selectable as research-only patterns."""
    labs = load_catalog()
    return {
        "labs": labs,
        "n": len(labs),
        "n_testable": sum(1 for l in labs if l["testable"]),
        "categories": sorted({l["category"] for l in labs if l["category"]}),
    }


@router.get("/syndromes")
def get_syndromes():
    """All saved custom syndromes (newest first).

    `storage` tells the UI where they are kept: "motherduck" survives a redeploy,
    "file" only lasts as long as this container does.
    """
    return {"items": list_custom(), "storage": pattern_store.backend_name()}


@router.post("/syndromes")
def post_syndrome(body: SyndromeIn, background: BackgroundTasks):
    """Create or update a custom syndrome.

    Editing the rules invalidates any cohort ranking built from the old ones, so
    the cache is dropped immediately and rebuilt in the background — the save
    returns straight away rather than waiting on a full-cohort pass.
    """
    try:
        record = save_custom(
            name=body.name, description=body.description,
            signals=[s.model_dump() for s in body.signals],
            min_signals=body.min_signals, key=body.key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    pattern_risk.clear(record["key"])
    background.add_task(pattern_risk.build, record)
    return record


@router.delete("/syndromes/{key}")
def remove_syndrome(key: str):
    if not delete_custom(key):
        raise HTTPException(404, "No such custom syndrome.")
    pattern_risk.clear(key)
    return {"deleted": key}


@router.post("/syndromes/{key}/rank")
def rank_syndrome(key: str):
    """Score the whole cohort against one pattern and cache the ranking.

    Normally this happens in the background on save; this endpoint is for
    rebuilding on demand, and it reports how many admissions ranked.
    """
    record = get_custom(key)
    if not record:
        raise HTTPException(404, "No such custom syndrome.")
    n = pattern_risk.build(record)
    if n == 0:
        raise HTTPException(
            400, "This pattern has no rule over a lab in the dataset, so the "
                 "cohort can't be ranked by it.")
    return {"pattern": key, "n_ranked": n}


@router.get("/export")
def export_syndromes():
    """Every saved pattern as a portable payload the user can download.

    Insurance against an ephemeral store: a researcher can keep their work even
    if the server it was built on is rebuilt from scratch.
    """
    return {"version": 1, "items": list_custom()}


@router.post("/import")
def import_syndromes(body: ImportRequest):
    """Merge an exported payload back in.

    Every item goes through `save_custom` so an imported file gets exactly the
    same validation as something built in the UI — a hand-edited export can't
    smuggle in a malformed rule. Items that fail are reported, not fatal.
    """
    imported, failed = [], []
    for item in body.items:
        try:
            record = save_custom(
                name=item.name, description=item.description,
                signals=[s.model_dump() for s in item.signals],
                min_signals=item.min_signals, key=item.key,
            )
            imported.append(record["key"])
        except ValueError as e:
            failed.append({"name": item.name, "reason": str(e)})
    if not imported and failed:
        raise HTTPException(400, f"Nothing could be imported: {failed[0]['reason']}")
    return {"imported": imported, "n_imported": len(imported), "failed": failed}


@router.post("/run")
def run(body: RunRequest):
    """Apply a rule set to every admission and report the matches."""
    con = connect()
    try:
        return run_on_cohort(
            con, [s.model_dump() for s in body.signals], body.min_signals)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        con.close()


# ── AI co-work turn (live web search) ─────────────────────────────────────────

def _extract_proposals(text: str) -> tuple[str, list[dict]]:
    """Pull the ```json {"proposals": [...]} block out of the reply.

    Returns (prose_without_block, proposals). Tolerant of a missing/broken
    block — proposals just come back empty and the prose is shown as-is.
    """
    proposals: list[dict] = []
    prose = text

    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for p in data.get("proposals", []) or []:
            direction = str(p.get("direction", "")).lower()
            if direction not in ("high", "low"):
                continue
            name_in = p.get("lab") or p.get("name") or ""
            itemid, name, in_dataset = resolve_lab(p.get("itemid"), name_in)
            if itemid is None and not name:
                continue
            cite = p.get("citation") or {}
            proposals.append({
                "itemid": itemid,
                "name": name,
                "direction": direction,
                "in_dataset": in_dataset,
                "rationale": (p.get("rationale") or "").strip(),
                "evidence": (p.get("evidence") or "").strip(),
                "citation": {
                    "title": (cite.get("title") or "").strip(),
                    "url": (cite.get("url") or "").strip(),
                },
            })
        prose = prose.replace(m.group(0), "").strip()

    # de-dupe by (itemid or lowercased name, direction); first proposal wins
    seen, unique = set(), []
    for p in proposals:
        k = (p["itemid"] if p["itemid"] is not None else p["name"].lower(), p["direction"])
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return prose, unique


def _collect_citations(resp) -> list[dict]:
    """Gather the real URLs the web_search tool surfaced, from message
    annotations on the Responses output. Best-effort and defensive."""
    out, seen = [], set()
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            for ann in getattr(content, "annotations", []) or []:
                url = getattr(ann, "url", None)
                if url and url not in seen:
                    seen.add(url)
                    out.append({"title": getattr(ann, "title", "") or url, "url": url})
    return out


def _build_input(req: ResearchRequest) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = f"Candidate syndrome: {req.name or '(unnamed)'}."
    if req.description:
        context += f" User's working description: {req.description}"
    msgs.append({"role": "system", "content": context})
    for turn in req.history[-10:]:
        role = "assistant" if turn.role in ("model", "assistant") else "user"
        msgs.append({"role": role, "content": turn.text})
    msgs.append({"role": "user", "content": req.message})
    return msgs


@router.post("/research")
def research(req: ResearchRequest):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(503, "Builder AI unavailable: OPENAI_API_KEY is not set.")
    if not req.message.strip():
        raise HTTPException(400, "Empty message.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    try:
        resp = client.responses.create(
            model=BUILDER_MODEL,
            tools=[{"type": "web_search"}],
            input=_build_input(req),
        )
        text = (getattr(resp, "output_text", "") or "").strip()
    except Exception as e:
        msg = str(e)
        if "insufficient_quota" in msg or "exceeded your current quota" in msg:
            raise HTTPException(402, "The builder AI is out of OpenAI credits — please top up.")
        if "rate_limit" in msg or "429" in msg:
            raise HTTPException(429, "The builder AI is rate-limited — try again in a minute.")
        if "401" in msg or "invalid_api_key" in msg or "Incorrect API key" in msg:
            raise HTTPException(503, "Builder AI unavailable: the OpenAI API key is missing or invalid.")
        if "web_search" in msg:
            raise HTTPException(
                502, "This OpenAI model/account doesn't support live web search. "
                     "Set OPENAI_BUILDER_MODEL to a web-search-capable model (e.g. gpt-4o).")
        raise HTTPException(502, f"Builder AI error: {type(e).__name__}: {e}")

    prose, proposals = _extract_proposals(text)
    return {
        "reply": prose or "Let me know which syndrome you'd like to build rules for.",
        "proposals": proposals,
        "citations": _collect_citations(resp),
    }
