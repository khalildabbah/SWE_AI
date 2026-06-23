# SWE-AI: Early Detection of Patient Deterioration Using Laboratory Test Trends

> A Software Engineering course project exploring how trends in routine laboratory tests can surface early signs of clinical deterioration in hospitalized patients.

**🔴 Live demo:** [deterioration-detector.onrender.com](https://deterioration-detector.onrender.com/)
*(free Render instance — the first request after idle takes ~30–60s to wake up)*

---

## 📌 Project Overview

Hospitalized patients often show measurable physiological changes in their laboratory results **hours before** a clinically obvious deterioration event. These early signals are frequently missed because clinicians review labs as isolated point-in-time values rather than as **trends over time**.

**SWE-AI** is a software system that ingests patient laboratory time-series data, analyzes how each patient's lab values evolve, and produces actionable outputs: abnormal trend detection, early-warning alerts, a per-patient risk score, and an interactive dashboard.

The goal is to demonstrate—through a working prototype—how trend-aware analysis of laboratory data can support earlier recognition of patient deterioration.

---

## ❓ Research Question

> **How can laboratory test trends over time be used to detect early signs of patient deterioration in hospitalized patients?**

---

## 🎯 Expected Artifact

A software system that receives patient laboratory time-series data from the **MIMIC-III `LABEVENTS`** table and returns:

- **Abnormal lab trend detection** — identifies clinically meaningful changes in lab values over time.
- **Early warning alerts** — flags patients whose trends suggest possible deterioration.
- **Risk score per patient** — a quantitative score summarizing each patient's deterioration risk.
- **Early-warning lead time** — quantifies *how many hours ahead* the trend signal fires before the first abnormal flag.
- **Clinical syndrome detection** — recognizes multi-lab patterns (e.g. kidney, metabolic) rather than treating each lab in isolation.
- **Cited scoring rule book** — a transparent, source-referenced explanation of exactly how every score is decided.
- **Dashboard visualization** — an interactive view of trends, alerts, and scores.

---

## 🗂️ Dataset Description

This project uses the **MIMIC-III** clinical database, specifically the `LABEVENTS` table, which records laboratory measurements for patients.

### Main Input Fields

| Field         | Description                                                        |
|---------------|--------------------------------------------------------------------|
| `SUBJECT_ID`  | Unique identifier for an individual patient.                       |
| `HADM_ID`     | Unique identifier for a hospital admission.                        |
| `ITEMID`      | Identifier for the specific laboratory test/measurement.           |
| `CHARTTIME`   | Timestamp when the measurement was recorded.                       |
| `VALUENUM`    | Numeric value of the laboratory measurement.                       |

### Scale (full dataset)

The full `LABEVENTS` dump is **~1.8 GB / 27.8M rows**. After filtering to the 8 core labs and cleaning, the system works over:

| Metric | Value |
|--------|-------|
| Raw rows streamed | **27,854,055** |
| Clean measurements kept | **4,615,515** |
| Distinct patients | **45,411** |
| Hospital admissions | **57,238** |
| Core labs tracked | **8** |

> **Note on data access:** MIMIC-III is a restricted-access dataset. Use of the data requires completion of the required training and a signed data use agreement via [PhysioNet](https://physionet.org/content/mimiciii/). **No real patient data is included in this repository.** For convenience, a ~90 MB **fully synthetic** sample (`deterioration-detector/data/sample/LABEVENTS_sample.csv`) is bundled so the system runs end-to-end on a fresh clone with no download — see [Running the Prototype](#-running-the-prototype).

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MIMIC-III LABEVENTS                        │
│        (SUBJECT_ID, HADM_ID, ITEMID, CHARTTIME, VALUENUM)         │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────┐
                  │   1. Data Ingestion &     │
                  │      Preprocessing        │
                  │  (clean, filter, resample)│
                  └────────────┬──────────────┘
                                │  patient lab time-series
                                ▼
                  ┌──────────────────────────┐        ┌──────────────────────┐
                  │   Storage layer           │ ─────▶ │  MotherDuck (cloud)   │
                  │  (DuckDB / MotherDuck)    │        │   full dataset, 10GB  │
                  └────────────┬──────────────┘        │   free tier           │
                                │                       └──────────────────────┘
                                ▼   (local labs.duckdb fallback)
                  ┌──────────────────────────┐
                  │   2. Trend Analysis &     │
                  │     Abnormality Detection │
                  └────────────┬──────────────┘
                                │  detected trends / anomalies
                                ▼
                  ┌──────────────────────────┐
                  │   3. Risk Scoring,        │
                  │   Trajectory, Syndromes,  │
                  │   Lead-Time & Alerts      │
                  └────────────┬──────────────┘
                                │  risk scores + alerts + evaluation
                                ▼
                  ┌──────────────────────────┐
                  │   4. Dashboard &          │
                  │      Visualization        │
                  │   (FastAPI + React)       │
                  └──────────────────────────┘
```

The system follows a **pipeline architecture**: data flows from ingestion through analysis and scoring, ending in a visualization layer. A single **storage layer** ([`src/storage/db.py`](deterioration-detector/src/storage/db.py)) is the only thing that touches the database, so the same code runs against the local DuckDB file or the hosted MotherDuck database depending on configuration.

---

## 🧩 Main Components

1. **Data Ingestion & Preprocessing** — streams `LABEVENTS` with DuckDB (no full RAM load), filters to the 8 core labs, drops non-numeric and implausible values, dedupes, and builds a compact analytical database.
2. **Trend Analysis & Abnormality Detection** — computes how each lab evolves over time and classifies values against reference ranges ([`trends.py`](deterioration-detector/src/analysis/trends.py), [`abnormal.py`](deterioration-detector/src/analysis/abnormal.py)).
3. **Risk Scoring, Trajectory & Alerts** — aggregates trends into a per-patient risk score, recomputes it at each timestamp to plot a **risk trajectory**, and emits early-warning **alerts** ([`risk_score.py`](deterioration-detector/src/analysis/risk_score.py), [`trajectory.py`](deterioration-detector/src/analysis/trajectory.py), [`alerts.py`](deterioration-detector/src/analysis/alerts.py)).
4. **Syndrome Detection** — recognizes multi-lab patterns (kidney, metabolic, etc.) rather than treating each lab independently ([`syndromes.py`](deterioration-detector/src/analysis/syndromes.py)).
5. **Lead-Time Analysis** — quantifies how many hours *ahead* the trend signal fires versus MIMIC's own abnormal `FLAG` — the scientific core of the project ([`lead_time.py`](deterioration-detector/src/analysis/lead_time.py)).
6. **Detector Evaluation** — scores our anomaly detector against MIMIC's `FLAG` column as ground truth ([`evaluation.py`](deterioration-detector/src/analysis/evaluation.py)).
7. **Scoring Rule Book** — a transparent, source-cited summary of how every score is decided, assembled *live* from the scoring engine's own constants so it can never drift from the code ([`rules.py`](deterioration-detector/src/analysis/rules.py)).
8. **Dashboard & API** — FastAPI serves the analysis over a JSON API and hosts the React dashboard.

---

## 🗄️ Data & Hosting

Because the full dataset is far larger than GitHub's 100 MB file limit, the database is **not** stored in git. Instead the storage layer resolves a connection in this order:

1. **MotherDuck (cloud)** — if `MOTHERDUCK_TOKEN` is set, the app connects to the hosted `labs` database (cloud DuckDB). This holds the **full 4.6M-row dataset** and is what the live Render deployment uses. The free tier gives 10 GB storage / 10 GB monthly compute.
2. **Local DuckDB file** — otherwise it falls back to `data/processed/labs.duckdb`, the file produced by `build_db.py` on your machine.
3. **Bundled sample** — if neither the real CSV nor a built DB is present, `build_db.py` ingests the bundled ~90 MB synthetic sample, so a fresh clone still runs end-to-end.

### Uploading the full dataset to MotherDuck

After building the database locally, push it to the cloud so every clone shares the real data:

```bash
cd deterioration-detector
export MOTHERDUCK_TOKEN="<token from MotherDuck UI → Settings → Access Tokens>"
.venv/bin/python scripts/upload_to_motherduck.py   # pushes every table to the cloud "labs" db
```

The script is safe to re-run (each table is replaced from the local copy) and prints per-table row counts.

### Configuring the token

The token is a **secret** and is never committed. Set it via a gitignored `.env` file (auto-loaded by the app):

```bash
cp .env.example .env
# then edit .env and paste your token:
#   MOTHERDUCK_TOKEN=...
```

> ⚠️ **Token expiry:** access tokens can be time-limited. If `/api/stats` suddenly reports small numbers, the token has expired and the app has silently fallen back to the sample — create a new token, then update it both in `.env` and in the Render dashboard's environment variables.

### Verifying which dataset is live

`/api/stats` reports the row/patient/admission counts — the fingerprint that distinguishes the real dataset from the sample:

```bash
curl -s https://deterioration-detector.onrender.com/api/stats | python3 -m json.tool
```

`admissions: 57238` (and `kept_rows: 4615515`) confirms the **full cloud dataset** is being served; small numbers mean the sample fallback is in use.

---

## 🛠️ Technology Stack

| Layer                  | Technology                                   |
|------------------------|----------------------------------------------|
| Language               | Python 3                                     |
| Ingestion / storage    | **DuckDB 1.5.3** (streams the 1.8 GB CSV, no full RAM load) |
| Hosted database        | **MotherDuck** (cloud DuckDB, free tier — full dataset) |
| Config                 | **python-dotenv** (`.env` for secrets)       |
| Analysis engine        | Pure Python (`src/analysis`), unit-tested with **pytest** |
| API                    | **FastAPI** + uvicorn                        |
| Dashboard / UI         | **React** (Vite) + **Recharts**              |
| Packaging / deploy     | **Docker** (multi-stage) + **Render** (`render.yaml` blueprint) |
| Version control / CI   | Git & GitHub + GitHub Actions                |

> DuckDB is pinned to **1.5.3** because MotherDuck does not yet support 1.5.4.

---

## 🚀 Running the Prototype

The working prototype lives in [`deterioration-detector/`](deterioration-detector/)
(full details in its [README](deterioration-detector/README.md)). It runs on a fresh
clone with **no MIMIC download** — `build_db.py` auto-falls back to the bundled
synthetic sample when the real dataset is absent.

```bash
cd deterioration-detector
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/build_db.py      # M1+M2: builds clean labs.duckdb (uses sample if no real CSV)
python scripts/build_risk.py    # M3-M6: scores every admission
uvicorn src.api.main:app --reload   # API on http://localhost:8000

# in a second terminal, for the dashboard:
cd frontend && npm install && npm run dev   # http://localhost:5173
```

**To run against the full cloud dataset instead of building locally**, set your
`MOTHERDUCK_TOKEN` (see [Data & Hosting](#-data--hosting)) — `build_risk.py` and the API
will read from MotherDuck automatically, no local build required.

> **You only see data after the build steps run (or a token is set)** — the database
> itself is not committed (it's generated). Drop the real `data/raw/LABEVENTS.csv` in
> place first to build against MIMIC-III instead of the synthetic sample.

### Running with Docker

The repo ships a multi-stage `Dockerfile` (FastAPI serves the built React dashboard and the `/api` routes from one image):

```bash
docker build -t deterioration-detector .
docker run -p 8000:8000 -e MOTHERDUCK_TOKEN="<token>" deterioration-detector
```

### Deploying to Render

[`render.yaml`](render.yaml) is a Render Blueprint — connect the repo to Render and it deploys the Docker image as a free web service (health check on `/api/stats`, auto-deploy on push). Add `MOTHERDUCK_TOKEN` as an environment variable in the Render dashboard so the deployment reads the full cloud dataset.

---

## 🔌 API Endpoints

| Endpoint | Returns |
|----------|---------|
| `GET /api/stats` | Pipeline scale stats + risk distribution (also the health check). |
| `GET /api/evaluation` | Detector-vs-MIMIC-`FLAG` accuracy, overall and per-lab. |
| `GET /api/lead-time` | How many hours ahead the trend signal fires before the first abnormal flag. |
| `GET /api/rules` | The cited scoring rule book: reference ranges, classification bands, point math, risk categories, and syndrome definitions, each tagged with a published source. |
| `GET /api/admissions` | Triage list of admissions ranked by risk (filterable by category). |
| `GET /api/admissions/{subject_id}/{hadm_id}` | Full detail for one admission: labs over time, trajectory, alerts, syndromes. |

---

## 🖥️ Using the Dashboard

- **Opens ready to read.** The dashboard auto-selects the highest-risk patient on load, so the detail pane is never empty — no "pick a patient" dead end.
- **Triage board (left).** Admissions are ranked by risk score. Use the **High / Medium / Low / All** filter to switch cohorts; the top patient of each cohort loads automatically.
- **Built-in glossary — hover anything.** Because this audience isn't clinical, every term explains itself on hover: lab names, the risk score, the High/Medium/Low badges, the `critical` / `worsening` counts, and the pipeline stats. A **dotted underline** marks anything you can hover.
- **Detail pane (right), top to bottom:** the overall **risk score + category**, the **risk trajectory** across the stay, auto-generated **early-warning alerts**, and each **lab plotted over time** with a green band marking the normal range.

### The 8 core labs (plain English)

| Lab | Normal range | What it tells you |
|-----|--------------|-------------------|
| Creatinine | 0.6–1.2 mg/dL | Kidney waste product; rising = kidneys not filtering well. |
| Urea Nitrogen (BUN) | 7–20 mg/dL | Protein-breakdown waste; high = kidney stress or dehydration. |
| Potassium | 3.5–5.0 mEq/L | Heart/muscle electrolyte; too high or low risks dangerous heart rhythms. |
| Sodium | 135–145 mEq/L | Controls water balance; abnormal levels affect brain and nerves. |
| Bicarbonate | 22–29 mEq/L | Blood acid balance; low = blood turning too acidic (distress). |
| White Blood Cells | 4–11 K/µL | Infection-fighting cells; high signals infection, very low weakens immunity. |
| Hematocrit | 36–48 % | Share of blood that is red cells; low = anemia/blood loss. |
| Lactate | 0.5–2.0 mmol/L | Builds up when tissues lack oxygen; rising = key warning of shock. |

> Reference ranges are generic adult values from [`lab_dictionary.py`](deterioration-detector/src/ingestion/lab_dictionary.py), for this educational prototype only — **not** clinical advice.

### 📖 Scoring Rule Book

The **Scoring Rule Book** tab is the dashboard's "show your work" page. Because this team isn't clinical, it makes every number in the app traceable — nothing is a black box. It walks through, in plain language:

1. **Reference ranges** — the normal range for each of the 8 labs and which direction signals deterioration.
2. **Classifying a value** — inside the range = *normal* (0 pts); just outside = *abnormal* (+1); more than half the range-width beyond = *critical* (+2).
3. **Building the score** — sum every lab's points, plus +1 if a lab is trending the wrong way *while already* out of range.
4. **Risk categories** — total **0–2 = Low**, **3–5 = Medium**, **6+ = High**.
5. **Clinical syndromes** — the named multi-lab patterns and how many signals must line up for each to fire.
6. **Sources** — every rule is tagged with a published reference (NEJM laboratory reference values, KDIGO, Sepsis-3, NEWS2). The parts that are this prototype's own scaling choices are honestly labelled *"engine heuristic,"* not attributed to a guideline.

The page is served by [`GET /api/rules`](#-api-endpoints), assembled **live from the scoring engine's own constants** ([`rules.py`](deterioration-detector/src/analysis/rules.py)) — so what you read can never drift from the code that actually scores patients.

---

## 📊 Current Project Status

✅ **Working prototype (Phase B), deployed**

- [x] Defined research question and project scope
- [x] Identified dataset and key input fields
- [x] Drafted system architecture and components
- [x] Set up data access and ingestion pipeline (DuckDB streaming)
- [x] Implement trend analysis & abnormality detection
- [x] Implement risk scoring, trajectory & alert engine
- [x] Add clinical syndrome detection
- [x] Add lead-time analysis & detector evaluation vs MIMIC `FLAG`
- [x] Add a cited scoring rule book (source-referenced, derived live from the engine)
- [x] Build dashboard visualization (FastAPI + React)
- [x] Testing & CI (pytest suite + GitHub Actions running the sample pipeline)
- [x] Host the full dataset on MotherDuck (cloud DuckDB)
- [x] Containerize (Docker) and deploy live on Render

---

## 🔜 Next Steps

1. Tune risk thresholds and add ICU-specific reference ranges.
2. Expand beyond the 8 core labs and add vitals where available.
3. Explore a learned risk model behind the existing `score_admission()` interface.
4. Add per-admission evaluation against outcomes and document findings.

---

## ⚠️ Disclaimer

**This project is an academic prototype developed for a Software Engineering course. It is NOT a medical device, clinical tool, or medical decision-support system.** It must **not** be used for real clinical decision-making, patient care, diagnosis, or treatment. The outputs are for educational and demonstration purposes only and have not been clinically validated or approved by any regulatory authority.

---

## 📄 License

To be determined.
