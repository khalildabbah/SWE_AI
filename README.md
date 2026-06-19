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

> **Note on data access:** MIMIC-III is a restricted-access dataset. Use of the data requires completion of the required training and a signed data use agreement via [PhysioNet](https://physionet.org/content/mimiciii/). **No patient data is included in this repository.**

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

| Layer                  | Proposed Technology                          |
|------------------------|----------------------------------------------|
| Language               | Python                                       |
| Data processing        | pandas, NumPy                                |
| Analysis / modeling    | scikit-learn, SciPy                          |
| Visualization / UI     | Streamlit / Dash (dashboard), Plotly / Matplotlib |
| Data storage           | CSV / SQLite (MIMIC-III subset)              |
| Version control        | Git & GitHub                                 |

> _The technology stack is provisional and may evolve as the project develops._

---

## 📊 Current Project Status

🚧 **Planning / Early Development**

- [x] Defined research question and project scope
- [x] Identified dataset and key input fields
- [x] Drafted system architecture and components
- [ ] Set up data access and ingestion pipeline
- [ ] Implement trend analysis & abnormality detection
- [ ] Implement risk scoring & alert engine
- [ ] Build dashboard visualization
- [ ] Testing, evaluation & documentation

---

## 🔜 Next Steps

1. Obtain access to the MIMIC-III dataset and prepare a working subset.
2. Build the data ingestion and preprocessing pipeline.
3. Define and prototype trend-detection logic for selected lab tests.
4. Develop the risk-scoring model and alerting thresholds.
5. Implement the dashboard for visualizing trends, alerts, and scores.
6. Evaluate the system and document findings.

---

## ⚠️ Disclaimer

**This project is an academic prototype developed for a Software Engineering course. It is NOT a medical device, clinical tool, or medical decision-support system.** It must **not** be used for real clinical decision-making, patient care, diagnosis, or treatment. The outputs are for educational and demonstration purposes only and have not been clinically validated or approved by any regulatory authority.

---

## 📄 License

To be determined.
