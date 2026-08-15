"""
Tests for the Pattern Builder API (src/api/builder):
proposal parsing out of the model's reply, citation collection, the co-work
endpoint's failure modes, and the CRUD / catalog / run / export-import routes.

The AI is never called for real — the OpenAI client is monkeypatched, so these
tests need no key, no network and no quota. Run:  pytest -q
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.builder as bld
import src.storage.pattern_store as ps

CREATININE = 50912
UREA = 51006


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point persistence at a temp JSON file and keep every test off MotherDuck
    and off the real OpenAI API, whatever the developer's environment has set."""
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ps, "STORE", tmp_path / "custom_syndromes.json")
    yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(bld.router)
    return TestClient(app)


# ── _extract_proposals: parsing the model's fenced JSON ──────────────────────

def _block(payload: dict) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


def test_extract_proposals_reads_a_valid_block():
    text = "Here is what I found.\n" + _block({"proposals": [{
        "lab": "Creatinine", "itemid": CREATININE, "direction": "high",
        "rationale": "Rises in AKI.", "evidence": "KDIGO defines AKI by a rise.",
        "citation": {"title": "KDIGO", "url": "https://kdigo.org"},
    }]})
    prose, proposals = bld._extract_proposals(text)

    assert "```" not in prose and prose == "Here is what I found."
    assert len(proposals) == 1
    p = proposals[0]
    assert p["itemid"] == CREATININE and p["name"] == "Creatinine"
    assert p["direction"] == "high" and p["in_dataset"] is True
    assert p["citation"] == {"title": "KDIGO", "url": "https://kdigo.org"}


def test_extract_proposals_survives_malformed_json():
    """A broken block must not lose the prose — the user still gets the reply."""
    text = "Some prose.\n```json\n{\"proposals\": [ oops \n```"
    prose, proposals = bld._extract_proposals(text)
    assert proposals == []
    assert "Some prose." in prose


def test_extract_proposals_with_no_block_at_all():
    prose, proposals = bld._extract_proposals("Just discussion, no rules yet.")
    assert proposals == []
    assert prose == "Just discussion, no rules yet."


def test_extract_proposals_drops_bad_direction_and_nameless_rules():
    text = _block({"proposals": [
        {"lab": "Creatinine", "direction": "sideways"},   # not high/low
        {"lab": "", "itemid": None, "direction": "high"},  # nothing to identify
        {"lab": "Lactate", "direction": "high"},           # keeper
    ]})
    _, proposals = bld._extract_proposals(text)
    assert [p["name"] for p in proposals] == ["Lactate"]


def test_extract_proposals_dedupes_same_lab_and_direction():
    text = _block({"proposals": [
        {"lab": "Creatinine", "direction": "high", "rationale": "first"},
        {"lab": "Creatinine", "direction": "high", "rationale": "second"},
        {"lab": "Creatinine", "direction": "low"},  # other direction stays
    ]})
    _, proposals = bld._extract_proposals(text)
    assert len(proposals) == 2
    assert proposals[0]["rationale"] == "first"  # first one wins


def test_extract_proposals_marks_non_dataset_labs_research_only():
    text = _block({"proposals": [
        {"lab": "Total Bilirubin", "itemid": None, "direction": "high"},
    ]})
    _, proposals = bld._extract_proposals(text)
    assert proposals[0]["itemid"] is None
    assert proposals[0]["in_dataset"] is False


def test_extract_proposals_ignores_a_bogus_itemid_but_keeps_the_name():
    """A hallucinated itemid must not smuggle a lab into the runnable set."""
    text = _block({"proposals": [{"lab": "Ferritin", "itemid": 999999, "direction": "high"}]})
    _, proposals = bld._extract_proposals(text)
    assert proposals[0]["itemid"] is None and proposals[0]["in_dataset"] is False
    assert proposals[0]["name"] == "Ferritin"


# ── _collect_citations: the URLs web_search actually surfaced ────────────────

class FakeAnnotation:
    def __init__(self, url, title=""):
        self.url, self.title = url, title


class FakeContent:
    def __init__(self, annotations):
        self.annotations = annotations


class FakeOutputItem:
    def __init__(self, content):
        self.content = content


class FakeResponse:
    def __init__(self, output_text="", output=()):
        self.output_text, self.output = output_text, list(output)


def test_collect_citations_dedupes_by_url():
    resp = FakeResponse(output=[FakeOutputItem([FakeContent([
        FakeAnnotation("https://a.example", "A"),
        FakeAnnotation("https://a.example", "A again"),
        FakeAnnotation("https://b.example", ""),
    ])])])
    cites = bld._collect_citations(resp)
    assert [c["url"] for c in cites] == ["https://a.example", "https://b.example"]
    assert cites[1]["title"] == "https://b.example"  # falls back to the URL


def test_collect_citations_on_a_bare_response():
    assert bld._collect_citations(FakeResponse()) == []


# ── /research ────────────────────────────────────────────────────────────────

def test_research_without_a_key_is_unavailable(client):
    r = client.post("/api/builder/research", json={"message": "hello"})
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.json()["detail"]


def test_research_rejects_an_empty_message(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    r = client.post("/api/builder/research", json={"message": "   "})
    assert r.status_code == 400


def _patch_openai(monkeypatch, result):
    """Stand in for `from openai import OpenAI`. `result` is either a response
    object to return or an exception to raise."""
    class FakeResponses:
        def create(self, **kwargs):
            self.kwargs = kwargs
            if isinstance(result, Exception):
                raise result
            return result

    class FakeClient:
        def __init__(self, api_key=None):
            self.responses = FakeResponses()

    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(openai, "OpenAI", FakeClient)


def test_research_happy_path_returns_prose_and_proposals(client, monkeypatch):
    reply = "Creatinine rises in AKI.\n" + _block({"proposals": [
        {"lab": "Creatinine", "itemid": CREATININE, "direction": "high",
         "citation": {"title": "KDIGO", "url": "https://kdigo.org"}},
    ]})
    resp = FakeResponse(output_text=reply, output=[FakeOutputItem([FakeContent([
        FakeAnnotation("https://kdigo.org", "KDIGO")])])])
    _patch_openai(monkeypatch, resp)

    r = client.post("/api/builder/research", json={"name": "AKI", "message": "propose rules"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Creatinine rises in AKI."
    assert body["proposals"][0]["itemid"] == CREATININE
    assert body["citations"][0]["url"] == "https://kdigo.org"


def test_research_falls_back_to_a_prompt_when_the_reply_is_empty(client, monkeypatch):
    _patch_openai(monkeypatch, FakeResponse(output_text=""))
    r = client.post("/api/builder/research", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["reply"].strip() != ""


@pytest.mark.parametrize("message, expected", [
    ("Error code: 429 - insufficient_quota", 402),
    ("rate_limit exceeded", 429),
    ("Error code: 401 - invalid_api_key", 503),
    ("web_search is not supported for this model", 502),
    ("something else entirely", 502),
])
def test_research_maps_provider_errors_to_useful_statuses(client, monkeypatch, message, expected):
    _patch_openai(monkeypatch, RuntimeError(message))
    r = client.post("/api/builder/research", json={"message": "go"})
    assert r.status_code == expected
    assert r.json()["detail"]  # always says something actionable


def test_build_input_carries_context_and_trims_history():
    req = bld.ResearchRequest(
        name="AKI", description="kidney injury", message="latest",
        history=[bld.ResearchTurn(role="user" if i % 2 == 0 else "model", text=f"t{i}")
                 for i in range(14)],
    )
    msgs = bld._build_input(req)
    assert msgs[0]["role"] == "system"
    assert "AKI" in msgs[1]["content"] and "kidney injury" in msgs[1]["content"]
    assert msgs[-1] == {"role": "user", "content": "latest"}
    # only the last 10 turns of history are replayed, plus 2 system + 1 user
    assert len(msgs) == 13
    assert {m["role"] for m in msgs[2:]} <= {"user", "assistant"}


# ── labs + catalog ───────────────────────────────────────────────────────────

def test_labs_lists_the_eight_testable_labs(client):
    labs = client.get("/api/builder/labs").json()["labs"]
    assert len(labs) == 8
    assert {"itemid", "name", "unit", "normal_low", "normal_high"} <= labs[0].keys()


def test_catalog_reports_totals_and_flags_testable_labs(client):
    body = client.get("/api/builder/catalog").json()
    assert body["n"] == len(body["labs"]) > 8
    assert body["n_testable"] == 8
    assert body["categories"] == sorted(body["categories"])
    assert all({"itemid", "label", "testable"} <= lab.keys() for lab in body["labs"])


def test_catalog_is_empty_when_the_csv_is_missing(client, monkeypatch, tmp_path):
    import src.analysis.lab_catalog as lc
    monkeypatch.setattr(lc, "CATALOG_CSV", tmp_path / "absent.csv")
    monkeypatch.setattr(lc, "_CACHE", None)
    body = client.get("/api/builder/catalog").json()
    assert body["labs"] == [] and body["n"] == 0


# ── syndrome CRUD ────────────────────────────────────────────────────────────

def test_syndrome_crud_roundtrip(client):
    created = client.post("/api/builder/syndromes", json={
        "name": "Test AKI", "description": "kidneys",
        "signals": [{"itemid": CREATININE, "direction": "high"},
                    {"itemid": UREA, "direction": "high"}],
        "min_signals": 2,
    })
    assert created.status_code == 200
    key = created.json()["key"]

    listed = client.get("/api/builder/syndromes").json()
    assert [s["key"] for s in listed["items"]] == [key]
    assert listed["storage"] == "file"

    assert client.delete(f"/api/builder/syndromes/{key}").status_code == 200
    assert client.get("/api/builder/syndromes").json()["items"] == []


@pytest.mark.parametrize("payload", [
    {"name": "", "signals": [{"itemid": CREATININE, "direction": "high"}]},
    {"name": "No rules", "signals": []},
    {"name": "Only junk", "signals": [{"itemid": CREATININE, "direction": "sideways"}]},
])
def test_saving_an_invalid_syndrome_is_a_400(client, payload):
    assert client.post("/api/builder/syndromes", json=payload).status_code == 400


def test_deleting_an_unknown_syndrome_is_a_404(client):
    assert client.delete("/api/builder/syndromes/custom_nope").status_code == 404


# ── export / import ──────────────────────────────────────────────────────────

def test_export_import_roundtrip(client):
    client.post("/api/builder/syndromes", json={
        "name": "Portable", "signals": [{"itemid": UREA, "direction": "high"}], "min_signals": 1})
    exported = client.get("/api/builder/export").json()
    assert exported["version"] == 1 and len(exported["items"]) == 1

    key = exported["items"][0]["key"]
    client.delete(f"/api/builder/syndromes/{key}")
    assert client.get("/api/builder/syndromes").json()["items"] == []

    r = client.post("/api/builder/import", json={"items": exported["items"]})
    assert r.status_code == 200 and r.json()["n_imported"] == 1
    restored = client.get("/api/builder/syndromes").json()["items"]
    assert restored[0]["name"] == "Portable"
    assert restored[0]["signals"][0]["itemid"] == UREA


def test_import_reports_bad_items_without_losing_the_good_ones(client):
    r = client.post("/api/builder/import", json={"items": [
        {"name": "Good", "signals": [{"itemid": UREA, "direction": "high"}]},
        {"name": "Bad", "signals": []},
    ]})
    assert r.status_code == 200
    assert r.json()["n_imported"] == 1
    assert r.json()["failed"][0]["name"] == "Bad"


def test_import_of_an_entirely_invalid_payload_is_a_400(client):
    r = client.post("/api/builder/import", json={"items": [{"name": "Bad", "signals": []}]})
    assert r.status_code == 400


# ── /run ─────────────────────────────────────────────────────────────────────

class FakeCon:
    """Minimal DuckDB stand-in: the COUNT(*) query gets a total, everything else
    gets the latest-value rows."""
    def __init__(self, rows, total):
        self.rows, self.total = rows, total

    def execute(self, sql, params=None):
        class R:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

            def fetchone(self):
                return self._rows[0]
        return R([(self.total,)]) if "COUNT(*)" in sql else R(self.rows)

    def close(self):
        pass


def test_run_reports_matches(client, monkeypatch):
    rows = [(1, 1, CREATININE, 2.0), (1, 1, UREA, 30.0),
            (2, 2, CREATININE, 2.5), (2, 2, UREA, 10.0)]
    monkeypatch.setattr(bld, "connect", lambda: FakeCon(rows, total=2))
    r = client.post("/api/builder/run", json={
        "signals": [{"itemid": CREATININE, "direction": "high"},
                    {"itemid": UREA, "direction": "high"}],
        "min_signals": 2})
    body = r.json()
    assert r.status_code == 200
    assert body["n_matched"] == 1 and body["total_admissions"] == 2
    assert body["examples"][0]["subject_id"] == 1


def test_run_without_valid_rules_is_a_400(client, monkeypatch):
    monkeypatch.setattr(bld, "connect", lambda: FakeCon([], total=0))
    r = client.post("/api/builder/run", json={"signals": [], "min_signals": 1})
    assert r.status_code == 400
