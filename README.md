# SWE-AI: Early Detection of Patient Deterioration Using Laboratory Test Trends

> A Software Engineering course project exploring how trends in routine laboratory tests can surface early signs of clinical deterioration in hospitalized patients.

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
                  ┌──────────────────────────┐
                  │   2. Trend Analysis &     │
                  │     Abnormality Detection │
                  └────────────┬──────────────┘
                                │  detected trends / anomalies
                                ▼
                  ┌──────────────────────────┐
                  │   3. Risk Scoring &       │
                  │      Alert Engine         │
                  └────────────┬──────────────┘
                                │  risk scores + alerts
                                ▼
                  ┌──────────────────────────┐
                  │   4. Dashboard &          │
                  │      Visualization        │
                  └──────────────────────────┘
```

The system follows a **pipeline architecture**: data flows from ingestion through analysis and scoring, ending in a visualization layer that presents results to the user.

---

## 🧩 Main Components

1. **Data Ingestion & Preprocessing**
   - Loads laboratory records from the `LABEVENTS` table.
   - Cleans and filters data, handles missing values, and organizes measurements into per-patient time-series.

2. **Trend Analysis & Abnormality Detection**
   - Computes how each lab value changes over time.
   - Detects abnormal trends and deviations from expected ranges.

3. **Risk Scoring & Alert Engine**
   - Aggregates detected trends into a per-patient risk score.
   - Generates early-warning alerts when risk thresholds are crossed.

4. **Dashboard & Visualization**
   - Displays lab trends, alerts, and risk scores in an interactive interface for review.

---

## 👥 Team Responsibilities

| Member        | Responsibility                                              |
|---------------|-------------------------------------------------------------|
| _TBD_         | Data ingestion & preprocessing                              |
| _TBD_         | Trend analysis & abnormality detection                      |
| _TBD_         | Risk scoring & alert engine                                 |
| _TBD_         | Dashboard & visualization                                   |
| _TBD_         | Documentation, testing & integration                        |

> _Team member names and detailed role assignments will be filled in as the project progresses._

---

## 🛠️ Technology Stack

| Layer                  | Technology                                   |
|------------------------|----------------------------------------------|
| Language               | Python                                       |
| Ingestion / storage    | **DuckDB** (streams the 1.8 GB CSV, no full RAM load) |
| Analysis engine        | Pure Python (`src/analysis`), unit-tested with **pytest** |
| API                    | **FastAPI** + uvicorn                        |
| Dashboard / UI         | **React** (Vite) + **Recharts**              |
| Version control / CI   | Git & GitHub + GitHub Actions                |

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

> **You only see data after the build steps run** — the database itself is not
> committed (it's generated). Drop the real `data/raw/LABEVENTS.csv` in place first
> to run against MIMIC-III instead of the synthetic sample.

---

## 📊 Current Project Status

✅ **Working prototype (Phase B)**

- [x] Defined research question and project scope
- [x] Identified dataset and key input fields
- [x] Drafted system architecture and components
- [x] Set up data access and ingestion pipeline (DuckDB streaming)
- [x] Implement trend analysis & abnormality detection
- [x] Implement risk scoring & alert engine
- [x] Build dashboard visualization (FastAPI + React)
- [x] Testing & CI (pytest suite + GitHub Actions running the sample pipeline)

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
