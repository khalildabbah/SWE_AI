"""
Tests for adding and deleting admissions (src/storage/mutations + the
POST/DELETE /api/admissions routes).

Every test runs against a throwaway DuckDB built by the fixture below, so the
real data/processed/labs.duckdb is never touched. Run:  pytest -q
"""
from datetime import datetime, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

import src.storage.db as db
from src.analysis.risk_score import LabState, score_admission
from src.storage import mutations

LACTATE, CREATININE, POTASSIUM = 50813, 50912, 50971
SUBJ, HADM = 90001, 80001
T0 = datetime(2150, 5, 1, 8, 0)

DERIVED = ("labs_clean", "admissions", "risk_summary", "lead_time")


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """A minimal copy of the real schema, plus one pre-existing MIMIC admission
    so 'did the write disturb anything else' is a question we can ask."""
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    path = tmp_path / "labs.duckdb"

    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE labs_clean(
        subject_id INTEGER, hadm_id INTEGER, itemid INTEGER, test_name VARCHAR,
        charttime TIMESTAMP, value DOUBLE, unit VARCHAR, flag VARCHAR)""")
    con.execute("""CREATE TABLE admissions(
        subject_id INTEGER, hadm_id INTEGER, n_measurements BIGINT, n_labs BIGINT,
        first_time TIMESTAMP, last_time TIMESTAMP, span_hours BIGINT)""")
    con.execute("""CREATE TABLE risk_summary(
        subject_id INTEGER, hadm_id INTEGER, score INTEGER, category VARCHAR,
        n_high INTEGER, n_worsening INTEGER)""")
    con.execute("""CREATE TABLE lead_time(
        subject_id INTEGER, hadm_id INTEGER,
        deteriorated BOOLEAN, concerned BOOLEAN, alerted BOOLEAN,
        event_hours DOUBLE, concern_hours DOUBLE, alert_hours DOUBLE,
        lead_concern_hours DOUBLE, lead_alert_hours DOUBLE, event_lab VARCHAR)""")
    con.execute("CREATE TABLE pipeline_stats(metric VARCHAR, value VARCHAR)")

    # An existing admission, as build_db.py would have left it (no source column).
    con.execute("INSERT INTO labs_clean VALUES (1, 11, ?, 'Creatinine', ?, 1.0, 'mg/dL', NULL)",
                [CREATININE, T0])
    con.execute("INSERT INTO admissions VALUES (1, 11, 1, 1, ?, ?, 0)", [T0, T0])
    con.execute("INSERT INTO risk_summary VALUES (1, 11, 0, 'Low', 0, 0)")
    con.execute("INSERT INTO lead_time VALUES (1, 11, false, false, false, "
                "NULL, NULL, NULL, NULL, NULL, NULL)")
    con.executemany("INSERT INTO pipeline_stats VALUES (?,?)",
                    [("raw_rows", "100"), ("kept_rows", "1"),
                     ("patients", "1"), ("admissions", "1")])
    con.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    yield path


def measurements(*triples):
    """(itemid, hours_offset, value) -> the payload shape the API takes."""
    return [{"itemid": iid, "charttime": (T0 + timedelta(hours=h)).isoformat(), "value": v}
            for iid, h, v in triples]


DETERIORATING = (
    (LACTATE, 0, 1.0), (LACTATE, 6, 3.5), (LACTATE, 12, 7.0),
    (CREATININE, 0, 0.9), (CREATININE, 6, 2.0), (CREATININE, 12, 3.6),
)


def rows_for(subject_id, hadm_id):
    con = db.connect()
    try:
        return {t: con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE subject_id = ? AND hadm_id = ?",
            [subject_id, hadm_id]).fetchone()[0] for t in DERIVED}
    finally:
        con.close()


def stats():
    con = db.connect()
    try:
        return dict(con.execute("SELECT metric, value FROM pipeline_stats").fetchall())
    finally:
        con.close()


# ── create ──────────────────────────────────────────────────────────────────

def test_create_populates_every_derived_table():
    result = mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))

    assert result["n_measurements"] == 6
    assert result["n_labs"] == 2
    assert rows_for(SUBJ, HADM) == {
        "labs_clean": 6, "admissions": 1, "risk_summary": 1, "lead_time": 1}


def test_create_scores_with_the_shared_engine():
    """The stored score must be what score_admission would produce — the write
    path must never grow its own copy of the maths."""
    result = mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))

    expected = score_admission([
        LabState(itemid=LACTATE, test_name="Lactate", unit="mmol/L",
                 latest_value=7.0, series=[1.0, 3.5, 7.0]),
        LabState(itemid=CREATININE, test_name="Creatinine", unit="mg/dL",
                 latest_value=3.6, series=[0.9, 2.0, 3.6]),
    ])
    assert (result["score"], result["category"]) == (expected.score, expected.category)

    con = db.connect()
    stored = con.execute(
        "SELECT score, category FROM risk_summary WHERE subject_id = ? AND hadm_id = ?",
        [SUBJ, HADM]).fetchone()
    con.close()
    assert stored == (expected.score, expected.category)


def test_create_records_span_and_counts():
    result = mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    assert result["span_hours"] == 12

    con = db.connect()
    adm = con.execute(
        "SELECT n_measurements, n_labs, span_hours FROM admissions "
        "WHERE subject_id = ? AND hadm_id = ?", [SUBJ, HADM]).fetchone()
    con.close()
    assert adm == (6, 2, 12)


def test_create_marks_provenance_and_leaves_existing_rows_as_mimic():
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))

    con = db.connect()
    new_rows = con.execute(
        "SELECT DISTINCT source FROM labs_clean WHERE subject_id = ?", [SUBJ]).fetchall()
    old_rows = con.execute(
        "SELECT DISTINCT source FROM labs_clean WHERE subject_id = 1").fetchall()
    con.close()

    assert new_rows == [("user",)]
    # Rows that predate the column came from the MIMIC extract.
    assert old_rows == [("mimic",)]


def test_create_updates_the_footer_counters():
    before = stats()
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    after = stats()

    assert int(after["kept_rows"]) == int(before["kept_rows"]) + 6
    assert int(after["patients"]) == int(before["patients"]) + 1
    assert int(after["admissions"]) == int(before["admissions"]) + 1
    # raw_rows counts the source CSV, which a hand-added admission cannot change.
    assert after["raw_rows"] == before["raw_rows"]


def test_create_does_not_disturb_other_admissions():
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    assert rows_for(1, 11) == {
        "labs_clean": 1, "admissions": 1, "risk_summary": 1, "lead_time": 1}


def test_a_single_reading_is_enough():
    result = mutations.create_admission(SUBJ, HADM, measurements((POTASSIUM, 0, 4.2)))
    assert result["n_measurements"] == 1
    assert result["category"] == "Low"


# ── validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label, subject_id, hadm_id, meas", [
    ("no measurements", SUBJ, HADM, []),
    ("unknown lab", SUBJ, HADM, measurements((999999, 0, 1.0))),
    ("value below plausible", SUBJ, HADM, measurements((LACTATE, 0, -5.0))),
    ("value above plausible", SUBJ, HADM, measurements((LACTATE, 0, 5000.0))),
    ("value not numeric", SUBJ, HADM, [{"itemid": LACTATE, "charttime": T0.isoformat(),
                                        "value": "high"}]),
    ("bad timestamp", SUBJ, HADM, [{"itemid": LACTATE, "charttime": "yesterday", "value": 1.0}]),
    ("missing timestamp", SUBJ, HADM, [{"itemid": LACTATE, "value": 1.0}]),
    ("zero subject id", 0, HADM, measurements((LACTATE, 0, 1.0))),
    ("negative hadm id", SUBJ, -3, measurements((LACTATE, 0, 1.0))),
    ("duplicate reading", SUBJ, HADM, measurements((LACTATE, 0, 1.0), (LACTATE, 0, 2.0))),
])
def test_create_rejects(label, subject_id, hadm_id, meas):
    with pytest.raises(mutations.ValidationError):
        mutations.create_admission(subject_id, hadm_id, meas)


def test_create_rejects_a_duplicate_admission():
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    with pytest.raises(mutations.ValidationError, match="already exists"):
        mutations.create_admission(SUBJ, HADM, measurements((POTASSIUM, 0, 4.0)))


def test_a_rejected_create_writes_nothing():
    before = stats()
    with pytest.raises(mutations.ValidationError):
        mutations.create_admission(
            SUBJ, HADM, measurements((LACTATE, 0, 1.0), (LACTATE, 6, 99999.0)))

    assert rows_for(SUBJ, HADM) == {t: 0 for t in DERIVED}
    assert stats() == before


def test_create_rejects_an_oversized_payload():
    too_many = [{"itemid": LACTATE, "charttime": (T0 + timedelta(minutes=i)).isoformat(),
                 "value": 1.0} for i in range(mutations.MAX_MEASUREMENTS + 1)]
    with pytest.raises(mutations.ValidationError, match="Too many"):
        mutations.create_admission(SUBJ, HADM, too_many)


# ── delete ──────────────────────────────────────────────────────────────────

def test_delete_removes_every_derived_row():
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    result = mutations.delete_admission(SUBJ, HADM)

    assert result["n_measurements"] == 6
    assert rows_for(SUBJ, HADM) == {t: 0 for t in DERIVED}


def test_delete_restores_the_footer_counters():
    before = stats()
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    mutations.delete_admission(SUBJ, HADM)
    assert stats() == before


def test_delete_leaves_other_admissions_alone():
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    mutations.delete_admission(SUBJ, HADM)
    assert rows_for(1, 11) == {
        "labs_clean": 1, "admissions": 1, "risk_summary": 1, "lead_time": 1}


def test_delete_of_an_unknown_admission_is_empty():
    assert mutations.delete_admission(4242, 4242) == {}


def test_exists_reflects_create_and_delete():
    assert not mutations.exists(SUBJ, HADM)
    mutations.create_admission(SUBJ, HADM, measurements(*DETERIORATING))
    assert mutations.exists(SUBJ, HADM)
    mutations.delete_admission(SUBJ, HADM)
    assert not mutations.exists(SUBJ, HADM)


# ── the HTTP routes ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    import src.api.main as main
    return TestClient(main.app)


def test_lab_catalog_route(client):
    body = client.get("/api/labs").json()
    assert len(body["items"]) == 8
    lactate = next(i for i in body["items"] if i["itemid"] == LACTATE)
    assert lactate["unit"] == "mmol/L"
    # The form validates against these before it will submit.
    assert lactate["plausible_min"] < lactate["normal_low"]


def test_post_then_delete_round_trip(client):
    payload = {"subject_id": SUBJ, "hadm_id": HADM,
               "measurements": measurements(*DETERIORATING)}

    created = client.post("/api/admissions", json=payload)
    assert created.status_code == 201
    assert created.json()["category"] in ("Low", "Medium", "High")

    assert client.get(f"/api/admissions/{SUBJ}/{HADM}").status_code == 200

    deleted = client.delete(f"/api/admissions/{SUBJ}/{HADM}")
    assert deleted.status_code == 200
    assert client.get(f"/api/admissions/{SUBJ}/{HADM}").status_code == 404


def test_post_reports_validation_as_400(client):
    body = {"subject_id": SUBJ, "hadm_id": HADM,
            "measurements": measurements((LACTATE, 0, 99999.0))}
    res = client.post("/api/admissions", json=body)
    assert res.status_code == 400
    assert "plausible" in res.json()["detail"]


def test_post_rejects_a_malformed_body_as_422(client):
    res = client.post("/api/admissions", json={"subject_id": SUBJ, "measurements": []})
    assert res.status_code == 422


def test_delete_of_an_unknown_admission_is_404(client):
    assert client.delete("/api/admissions/4242/4242").status_code == 404
