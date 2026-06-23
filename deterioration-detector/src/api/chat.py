"""
DATASET CHATBOT (OpenAI)
========================
A grounded Q&A agent that answers ONLY questions about this deterioration
dataset — patients, admissions, the 8 tracked labs, risk scores, alerts,
syndromes and cohort stats. It refuses anything off-topic (weather, general
medicine, etc.).

How it works:
  * The agent never sees the database. It is given a fixed set of read-only
    tools (src/api/chat_tools.py) and the model decides which to call via
    function calling. We run the tool-call loop ourselves so we control errors,
    the chart side-channel, and the conversation length.
  * Chart-producing tools append specs to a request-scoped list, which we return
    alongside the answer so the React widget renders the graph inline.

The OpenAI API key is read from OPENAI_API_KEY (.env locally / env var in
deploy) and stays server-side — it is never exposed to the browser.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.storage.db import connect
from src.api.chat_tools import build_toolset

router = APIRouter()

# Cheap, fast, solid tool-calling. Override with OPENAI_MODEL if desired.
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOOL_ROUNDS = 6  # safety cap on the function-calling loop

SYSTEM_PROMPT = """\
You are the assistant built into the "Patient Deterioration Detector" dashboard,
an educational software-engineering prototype. You answer questions about THIS
system's dataset only and you do it by calling the provided tools — never invent
numbers.

The dataset (MIMIC-III LABEVENTS) contains, per hospital admission, a time-series
of these 8 lab tests ONLY: Creatinine, Urea Nitrogen (BUN), Potassium, Sodium,
Bicarbonate, White Blood Cells, Hematocrit, Lactate. From these the system derives
a per-admission risk score (Low/Medium/High), early-warning alerts, clinical
syndromes, and a risk trajectory.

SCOPE — strict:
- Only answer questions about this dataset: patients (by SUBJECT_ID), admissions
  (HADM_ID), the 8 labs, risk scores, alerts, syndromes, lead time, cohort stats,
  and how the system works.
- If asked about anything else (weather, sports, general knowledge, other medical
  topics, coding help, etc.), politely refuse in one sentence and steer back to
  what you can answer.
- If the user asks about a lab that is NOT one of the 8 (e.g. blood sugar/glucose,
  blood pressure, temperature), say it is not tracked and list what is.

HOW TO ANSWER:
- A "patient" is identified by SUBJECT_ID; one patient may have several admissions.
  When given a patient id, call find_patient first. If there are multiple
  admissions, use the highest-risk one unless the user named a HADM_ID, and say
  which admission you used.
- When the user wants a trend, "graph", "chart", or "plot" of a lab, call
  get_lab_series with render_chart=true — the chart is shown to the user
  automatically; your text should briefly summarise it (latest value, range,
  direction), not dump every point.
- For "risk points / worsening / alerts" questions, use get_alerts or
  get_admission_detail. For "how many high-risk patients" or dataset size, use
  cohort_stats / list_high_risk_patients.
- "last 7 days / last month" windows are measured against each patient's own most
  recent measurement (dataset timestamps are de-identified and shifted), so pass
  last_n_days and briefly note the window is relative to their latest reading.
- Be concise and clear for a non-clinical reader. Use plain language and short
  bullet lists. This is an educational prototype, NOT medical advice — never give
  diagnosis or treatment guidance.
"""

# OpenAI tool (function) schemas — mirror the callables in chat_tools.build_toolset.
TOOLS = [
    {"type": "function", "function": {
        "name": "list_available_labs",
        "description": "List the 8 lab tests this system tracks, with units and normal ranges. "
                       "Call this to check whether a lab the user asked about exists at all.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "find_patient",
        "description": "Look up a patient by SUBJECT_ID and list their hospital admissions with each "
                       "admission's risk score/category. Use first when the user gives a patient id.",
        "parameters": {"type": "object", "properties": {
            "subject_id": {"type": "integer", "description": "The patient's SUBJECT_ID."}},
            "required": ["subject_id"]}}},
    {"type": "function", "function": {
        "name": "get_admission_detail",
        "description": "Full risk picture for one admission: overall risk score & category, per-lab "
                       "status/trend breakdown, early-warning alerts and detected clinical syndromes.",
        "parameters": {"type": "object", "properties": {
            "subject_id": {"type": "integer"}, "hadm_id": {"type": "integer"}},
            "required": ["subject_id", "hadm_id"]}}},
    {"type": "function", "function": {
        "name": "get_alerts",
        "description": "Early-warning alerts (risk points / worsening labs) for an admission. Pass "
                       "last_n_days > 0 to restrict to the most recent N days of that admission.",
        "parameters": {"type": "object", "properties": {
            "subject_id": {"type": "integer"}, "hadm_id": {"type": "integer"},
            "last_n_days": {"type": "integer", "description": "Optional window in days; 0 = whole stay."}},
            "required": ["subject_id", "hadm_id"]}}},
    {"type": "function", "function": {
        "name": "get_lab_series",
        "description": "Time-series of one lab for an admission, optionally windowed to the most recent "
                       "days. Set render_chart=true to also show the user an inline graph.",
        "parameters": {"type": "object", "properties": {
            "subject_id": {"type": "integer"}, "hadm_id": {"type": "integer"},
            "lab_name": {"type": "string", "description": "Lab name, e.g. 'Creatinine', 'lactate', 'BUN'."},
            "last_n_days": {"type": "integer", "description": "Optional window in days; omit for whole stay."},
            "render_chart": {"type": "boolean", "description": "Show an inline chart to the user."}},
            "required": ["subject_id", "hadm_id", "lab_name"]}}},
    {"type": "function", "function": {
        "name": "cohort_stats",
        "description": "Dataset-wide stats: pipeline scale (rows, patients, admissions) and the "
                       "Low/Medium/High risk distribution.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_high_risk_patients",
        "description": "Top admissions ranked by risk score. Optionally filter category to 'High', "
                       "'Medium' or 'Low'. Use to surface concrete patient/admission ids.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "limit": {"type": "integer", "description": "How many to return (max 50)."}},
            "required": []}}},
]


class ChatTurn(BaseModel):
    role: str   # "user" | "model"
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


def _build_messages(history: list[ChatTurn], message: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-12:]:  # keep recent context bounded
        role = "assistant" if turn.role in ("model", "assistant") else "user"
        messages.append({"role": role, "content": turn.text})
    messages.append({"role": "user", "content": message})
    return messages


@router.post("/api/chat")
def chat(req: ChatRequest):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(503, "Chatbot unavailable: OPENAI_API_KEY is not set.")
    if not req.message.strip():
        raise HTTPException(400, "Empty message.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    con = connect()
    charts: list = []
    try:
        tools = build_toolset(con, charts)
        by_name = {fn.__name__: fn for fn in tools}

        messages = _build_messages(req.history, req.message)
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS, temperature=0.2)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                reply = (msg.content or "").strip()
                break
            # record the assistant's tool-call turn, then answer each call
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                fn = by_name.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = fn(**args) if fn else {"error": f"unknown tool {tc.function.name}"}
                    if not isinstance(result, dict):
                        result = {"result": result}
                except Exception as te:
                    result = {"error": f"{type(te).__name__}: {te}"}
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                })

        reply = reply or (
            "I couldn't produce an answer for that — try rephrasing, or ask about "
            "a patient, their labs, the risk scores, or the dataset overall.")
    except Exception as e:  # surface a clean message instead of a 500 stack trace
        msg = str(e)
        if "insufficient_quota" in msg or "exceeded your current quota" in msg:
            raise HTTPException(402, "The chatbot is out of OpenAI credits — please top up the account.")
        if "rate_limit" in msg or "429" in msg:
            raise HTTPException(429, "The chatbot is rate-limited right now — please try again in a minute.")
        if "401" in msg or "invalid_api_key" in msg or "Incorrect API key" in msg:
            raise HTTPException(503, "Chatbot unavailable: the OpenAI API key is missing or invalid.")
        raise HTTPException(502, f"Chat backend error: {type(e).__name__}: {e}")
    finally:
        con.close()

    # de-dupe charts by title (the agent may fetch the same series twice)
    seen, unique_charts = set(), []
    for c in charts:
        if c["title"] not in seen:
            seen.add(c["title"])
            unique_charts.append(c)

    return {"reply": reply, "charts": unique_charts}
