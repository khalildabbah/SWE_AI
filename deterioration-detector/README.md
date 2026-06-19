# Patient Deterioration Detector

A software system that ingests hospital laboratory data (MIMIC-III `LABEVENTS`),
analyses lab **trends over time**, detects abnormal values and worsening patterns,
computes a per-patient **risk score**, and raises **early-warning alerts** — shown
on a web dashboard.

> **Research question:** *How can laboratory test trends over time be used to detect
> early signs of patient deterioration in hospitalized patients?*

This is an educational SWE-course prototype. The reference ranges and risk rules are
intentionally simple and transparent — **not** clinical advice.

---

## Architecture (8 modules)

```
LABEVENTS.csv (27.8M rows, 1.85 GB)
        │
M1 INGESTION  ─ DuckDB streams + filters the CSV (no full load into RAM)
M2 PREPROCESS ─ keep 8 core labs · drop text/sentinel values · map names · dedupe
        ▼  data/processed/labs.duckdb  (4.6M clean rows)
M3 TIME-SERIES ─ per-lab slope / monotonic run         ┐
M4 ANOMALY     ─ value vs reference range (normal/abnormal/critical)
M5 RISK SCORE  ─ severity + worsening → Low / Medium / High   ├─ src/analysis/  (pure, unit-tested)
M6 ALERTS      ─ explainable early-warning messages    ┘
        ▼
FastAPI backend (src/api)  ──►  React dashboard (frontend)
M7 DASHBOARD ─ triage board · lab timelines · risk trajectory · alerts
M8 TESTS+PERF ─ pytest suite · pipeline timing in /api/stats
```

| Layer | Tech |
|-------|------|
| Ingestion / preprocessing | Python + **DuckDB** |
| Storage | DuckDB file (`labs.duckdb`) |
| Analysis engine | Pure Python (`src/analysis`) |
| API | **FastAPI** + uvicorn |
| Dashboard | **React** (Vite) + **Recharts** |
| Tests | **pytest** |

---

## The 8 core labs

Creatinine · Urea Nitrogen (BUN) · Potassium · Sodium · Bicarbonate ·
White Blood Cells · Hematocrit · Lactate
(reference ranges in [`src/ingestion/lab_dictionary.py`](src/ingestion/lab_dictionary.py)).

## Risk score (transparent rule engine)

Per lab: `0` normal · `1` abnormal · `2` critical, plus `+1` if the value is
already out of range **and** trending worse over the last 3 measurements.
Sum → **Low (0–2) · Medium (3–5) · High (6+)**. Phase C can swap a learned model
behind the same `score_admission()` interface.

---

## Run it

### 1. Backend (Python)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# place the dataset at data/raw/LABEVENTS.csv (or symlink it)
python scripts/build_db.py      # M1+M2: 27.8M rows -> clean labs.duckdb (~7s)
python scripts/build_risk.py    # M3-M6: score all 57k admissions (~8s)

uvicorn src.api.main:app --reload   # API on http://localhost:8000  (docs at /docs)
```

### 2. Frontend (React)
```bash
cd frontend
npm install
npm run dev                      # dashboard on http://localhost:5173
```

### 3. Tests
```bash
pytest -q                        # M8: analysis-engine unit tests
```

---

## Pipeline results (full dataset)

| Metric | Value |
|--------|-------|
| Raw rows ingested | 27,854,055 |
| Clean values kept | 4,615,515 |
| Patients | 45,411 |
| Admissions | 57,238 |
| Ingestion time | ~7 s |

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/stats` | pipeline scale story + risk distribution |
| GET | `/api/admissions?category=High` | triage board, ranked by risk |
| GET | `/api/admissions/{subject_id}/{hadm_id}` | timelines, risk, trajectory, alerts |

## Known limitations (Phase B)

- Risk rules are heuristic, not clinically validated (tunable thresholds).
- 8 labs only; reference ranges are generic adult values, not ICU-specific.
- MIMIC dates are de-identified (shifted to future years) — treated as relative time.
- Alerts are computed on request, not streaming/real-time.
