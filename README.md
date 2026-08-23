# 🏥 LabTrend
## Early Detection of Patient Deterioration Using Laboratory Test Trends

LabTrend is an academic software project designed to identify early signs of patient deterioration by analyzing changes in laboratory test results over time.

Instead of looking only at individual laboratory values, LabTrend follows the patient's laboratory history and analyzes how results change over time. The system uses trend analysis, explainable risk-scoring rules, early-warning alerts, and interactive visualizations to help identify possible deterioration.

---

## 🌐 Project Resources

- **Project Website:**  
  https://sites.google.com/view/2026group5labtrend

- **User Manual:**  
  https://drive.google.com/uc?export=download&id=1afWsu6GJUGGy7OMCGq5ov4ZuRHdxTqvh

- **Live Application:**  
  https://deterioration-detector.onrender.com/

> The live application is hosted on a free Render instance, so the first request after a period of inactivity may take some time to load.

---

## ❓ Research Question

> **How can laboratory test trends over time be used to detect early signs of patient deterioration in hospitalized patients?**

---

## 🎯 Project Goal

The goal of LabTrend is to transform repeated laboratory measurements into useful early-warning information.

Many systems and clinical workflows focus on individual laboratory values. However, a value may become more meaningful when we also examine how it has changed over time.

LabTrend was developed to:

- Analyze laboratory results over time.
- Detect abnormal laboratory values.
- Identify worsening laboratory trends.
- Calculate an explainable patient risk score.
- Classify patients as Low, Medium, or High risk.
- Generate early-warning alerts.
- Detect patterns across multiple laboratory tests.
- Present patient information through an interactive dashboard.
- Allow researchers to define and test additional clinical patterns.

A major goal of the project is **explainability**. The system does not simply produce a risk category; it also provides information about the laboratory values, trends, and rules that contributed to that result.

---

# 🗂️ Dataset

LabTrend uses data based on the **MIMIC-III** critical-care research database, mainly the `LABEVENTS` table.

The LABEVENTS table contains laboratory measurements collected during hospital admissions.

Important fields include:

| Field | Description |
|---|---|
| `SUBJECT_ID` | Unique patient identifier |
| `HADM_ID` | Hospital admission identifier |
| `ITEMID` | Laboratory test identifier |
| `CHARTTIME` | Time when the measurement was recorded |
| `VALUENUM` | Numeric laboratory result |

### Dataset Scale

The original LABEVENTS dataset contains approximately:

- **27.8 million** laboratory records
- **45,000+** patients
- **57,000+** hospital admissions

LabTrend focuses on **8 core laboratory tests**.

After filtering and cleaning the original data, approximately **4.6 million clean laboratory measurements** remain for analysis.

### MIMIC-III Access

MIMIC-III is a restricted-access research dataset and the original patient data cannot be distributed publicly with this repository.

For this reason, the repository also includes **synthetic sample data** that allows the main system workflow to be demonstrated without providing restricted patient data.

---

# 🧹 Data Cleaning and Preprocessing

Before the system analyzes patients, the laboratory data goes through a cleaning and preparation process.

We started with approximately **27.8 million laboratory test records** from MIMIC-III.

The preprocessing pipeline:

1. Reads the large LABEVENTS dataset using DuckDB.
2. Filters the dataset to the 8 core laboratory tests used by LabTrend.
3. Removes non-numeric values.
4. Removes missing or implausible measurements.
5. Removes unnecessary or duplicate information where applicable.
6. Organizes measurements by patient, hospital admission, and time.
7. Stores the processed information in DuckDB.

After preprocessing, approximately **4.6 million clean measurements** remain.

Organizing the data by patient and time is especially important because LabTrend does not only examine the patient's latest laboratory value. It also examines previous measurements to understand how the value is changing over time.

---

# 🏗️ System Architecture

LabTrend follows a pipeline architecture.

```text
        MIMIC-III LABEVENTS
                 │
                 ▼
     Data Ingestion & Cleaning
                 │
                 ▼
        DuckDB / MotherDuck
                 │
                 ▼
   Trend & Abnormality Analysis
                 │
                 ▼
     Risk Scoring & Patterns
                 │
                 ▼
       Early-Warning Alerts
                 │
                 ▼
              FastAPI
                 │
                 ▼
        React + Vite Dashboard
```

## Main Architecture Components

### 1. Data Ingestion & Preprocessing

This component reads the laboratory dataset and prepares it for analysis.

DuckDB allows the system to process the large LABEVENTS dataset without loading the entire file into memory.

The component filters the data, cleans invalid measurements, and creates an organized analytical dataset.

---

### 2. Storage Layer

LabTrend supports:

- **DuckDB** for local data storage.
- **MotherDuck** for cloud-hosted DuckDB storage.

This allows the same analysis logic to work with either a local database or a cloud-hosted dataset.

---

### 3. Trend Analysis

The Trend Analysis component examines how laboratory values change over time.

Instead of asking only:

> Is this laboratory value abnormal?

LabTrend can also examine:

> Is this laboratory value getting better, remaining stable, or getting worse?

This provides additional information about the patient's trajectory.

---

### 4. Abnormality Detection

Laboratory values are compared with predefined reference ranges.

Measurements can be classified according to their relationship with the expected range.

This information is then used by the scoring and alerting components.

---

### 5. Risk Scoring

The Risk Scoring component combines information from multiple laboratory tests to calculate a patient risk score.

The score considers:

- Abnormal laboratory measurements.
- Critically abnormal measurements.
- Worsening laboratory trends.
- Multiple abnormal laboratory tests occurring together.

The result is translated into an understandable risk category.

---

### 6. Backend API

The backend is implemented using **FastAPI**.

It connects the data and analysis components with the frontend and provides the information required by the dashboard.

---

### 7. Dashboard

The frontend is built using **React and Vite**.

Recharts is used to visualize laboratory values, risk trajectories, and other patient information.

---

# ✨ Main Features

## 🧑‍⚕️ Patient Monitoring Dashboard

The Patient Monitoring Dashboard provides an overview of patient admissions and their calculated risk levels.

Patients can be filtered according to:

- 🟢 Low Risk
- 🟡 Medium Risk
- 🔴 High Risk

For each patient, the system can display:

- Current risk score
- Risk category
- Laboratory measurements
- Laboratory history
- Abnormal measurements
- Laboratory trends
- Early-warning alerts
- Risk trajectory
- Detected clinical patterns

This allows the user to move from a general overview of patients to a more detailed view of a specific patient's condition.

---

# 📈 Laboratory Trend Analysis

One of the main ideas behind LabTrend is that laboratory values should not always be viewed as isolated measurements.

For example, two patients may currently have similar laboratory values, but one patient's value may be stable while the other patient's value has been continuously worsening.

LabTrend therefore organizes measurements as time-series data and analyzes how each laboratory result changes over time.

The dashboard presents these changes visually so that the patient's laboratory trajectory is easier to understand.

---

# ⚠️ Early-Warning Alerts

LabTrend generates alerts based on abnormal laboratory values and worsening trends.

The purpose of these alerts is to highlight information that may require attention.

Instead of simply displaying that a laboratory measurement is abnormal, the system can also indicate that an already abnormal measurement is continuing to move in an unfavorable direction.

---

# 🎯 Explainable Risk Scoring

LabTrend uses a **rule-based scoring system**.

This was an important design decision because we wanted the system's output to remain understandable rather than relying only on a black-box prediction.

Each laboratory measurement can contribute to the patient's overall score.

The scoring logic considers:

- Whether the measurement is normal.
- Whether it is outside the reference range.
- How far it is outside the range.
- Whether the laboratory value is worsening over time.

The default risk categories are:

| Score | Risk Level |
|---:|---|
| **0–2** | 🟢 Low Risk |
| **3–5** | 🟡 Medium Risk |
| **6+** | 🔴 High Risk |

The user can therefore inspect the underlying laboratory information and understand why the patient received a particular risk category.

---

# 📖 Scoring Rule Book

The **Scoring Rule Book** is an important explainability feature in LabTrend.

It explains how the risk-scoring engine works and helps users understand how the system reaches its results.

The Rule Book includes:

### Laboratory Reference Ranges

It displays the reference range used for each of the 8 core laboratory tests.

### Value Classification

It explains how measurements are classified according to their relationship with the reference range.

For example:

- Normal
- Abnormal
- Critical

### Score Calculation

It explains how points are assigned to abnormal values and worsening trends.

### Risk Categories

It explains how the total score becomes:

- Low Risk
- Medium Risk
- High Risk

### Clinical Patterns

It also describes the multi-laboratory patterns used by the system.

### Sources

The scoring rules and reference information can be connected with supporting medical references.

An important design decision is that the Rule Book is generated from the same constants used by the actual scoring engine.

This helps prevent a situation where the documentation says one thing while the code performs a different calculation.

---

# 📉 Risk Trajectory

LabTrend does not only calculate the patient's latest risk score.

The system can recalculate risk at different points during the patient's hospital stay.

This creates a **risk trajectory** that shows how the calculated risk changes over time.

The trajectory can help identify whether the patient's calculated risk is:

- Increasing
- Decreasing
- Remaining relatively stable

This provides more context than viewing only one final risk score.

---

# 🧩 Clinical Pattern Detection

Some medical situations involve changes across multiple laboratory tests rather than one isolated measurement.

LabTrend therefore supports multi-laboratory pattern detection.

The system can examine combinations of laboratory abnormalities and trends and identify when a defined pattern appears in the patient's data.

These patterns can then be displayed together with the patient's risk and laboratory information.

---

# 🛠️ Pattern Builder

The **Pattern Builder** allows the system to go beyond its predefined clinical patterns.

Researchers can create their own laboratory-based pattern and test it against the available patient data.

The basic workflow is:

### Step 1 — Define a Pattern

The user chooses a disease, syndrome, or laboratory pattern they want to investigate.

### Step 2 — Select Laboratory Rules

The user can select relevant laboratory tests and define:

- Expected direction
- Thresholds
- Explanation
- Supporting evidence
- References

### Step 3 — AI-Assisted Research

The Pattern Builder can use the **OpenAI API** as an AI co-research assistant.

The AI can help investigate possible laboratory relationships and suggest relevant rules and sources.

The user remains responsible for reviewing the suggestions.

### Step 4 — Run the Pattern

The pattern can be tested against the available patient cohort.

The system then identifies admissions that match the defined rules.

### Step 5 — Save the Pattern

Saved patterns can be reused and displayed together with the built-in patterns.

---

# 🔄 Custom Pattern Risk Scoring

A pattern created using the Pattern Builder can also be used as an alternative scoring model.

The default LabTrend score answers a general question:

> **How abnormal does this patient's laboratory profile currently appear?**

A custom pattern can answer a more specific research question:

> **How strongly does this patient's laboratory history match this particular pattern?**

When a custom pattern is selected, the system can use its rules when calculating:

- Risk score
- Risk category
- Alerts
- Risk trajectory
- Patient ranking

This makes LabTrend more flexible for research and experimentation.

---

# 📊 Detector Evaluation

LabTrend includes functionality for evaluating its abnormality detector.

The detector can be compared with the abnormal `FLAG` information available in MIMIC-III.

The evaluation can include measurements such as:

- Accuracy
- Precision
- Recall
- Specificity
- F1 Score

These measurements help us understand how closely the system's abnormality classification agrees with the available reference information.

This evaluation represents **technical evaluation of the prototype** and should not be interpreted as clinical validation.

---

# ⏱️ Early-Warning Lead-Time Analysis

An important part of the research question is whether analyzing trends can provide information earlier than looking only at individual abnormal measurements.

LabTrend therefore includes **lead-time analysis**.

The system can examine the time difference between a trend-based warning and a later abnormal reference event.

This allows us to investigate whether changes over time can provide earlier warning signals.

---

# 🤖 AI Assistance

AI is used as an additional research and interaction component in LabTrend.

The OpenAI API supports functionality such as:

- Dataset-related question answering.
- Research assistance in the Pattern Builder.
- Suggestions for possible laboratory rules.
- Assistance with investigating clinical patterns.

The main patient risk score itself remains based on transparent rules rather than being generated directly by the language model.

This separation helps keep the main risk calculation explainable.

---

# 🧪 Add, Delete and Export Patient Features

The system also includes patient-management functionality developed as part of the software engineering process.

### Add Patient

Allows a user to add patient information for testing and demonstration purposes.

### Delete Patient

Allows user-created patient records to be removed from the system.

### Export Patient Report

Allows patient information and analysis results to be exported into a report.

These features were also useful during development for testing complete user workflows beyond the core analysis pipeline.

---

# 🛠️ Technologies

## Data & Analysis

- **Python** — main programming language.
- **DuckDB** — efficient processing of the large laboratory dataset.
- **pandas** — data manipulation and analysis.
- **Pydantic** — data validation.

## Backend

- **FastAPI** — REST API.
- **Uvicorn** — API server.
- **MotherDuck** — cloud-hosted DuckDB storage.

## Artificial Intelligence

- **OpenAI API** — dataset Q&A and AI-assisted research in the Pattern Builder.

## Frontend

- **React** — interactive user interface.
- **Vite** — frontend development and build environment.
- **Recharts** — laboratory and risk visualizations.

## Deployment

- **Docker** — application containerization.
- **Render** — application hosting.

## Testing & Development

- **pytest** — automated Python tests.
- **GitHub Actions** — continuous integration.
- **Git & GitHub** — source control and collaboration.

---

# 📊 System Evaluation Procedure

LabTrend was evaluated in several stages.

First, we tested the data-processing pipeline to make sure that laboratory measurements were correctly cleaned, filtered, and organized by patient and time.

We then tested the deterioration detection and risk-scoring rules on the processed data and checked whether the system correctly identified abnormal laboratory values and worsening trends.

We also evaluated the complete system workflow, from loading patient data to displaying risk scores, alerts, laboratory trends, and patient information in the dashboard.

The main system features were tested to make sure they worked correctly and consistently.

The abnormality detector was also compared with the abnormal `FLAG` information available in MIMIC-III.

As an additional evaluation, we presented LabTrend to a medical doctor and asked for feedback about:

- The project idea
- User interface
- Presentation of patient information
- Data reliability
- Possible clinical use

The feedback helped us identify both strengths of the system and areas that require further research and validation.

---

# 📋 Evaluation Results

The evaluation showed that LabTrend can process laboratory data, analyze changes over time, calculate explainable risk scores, and present the results through an interactive dashboard.

The system was able to identify abnormal laboratory values and worsening trends according to the rules defined in the analysis engine.

The complete workflow — from data processing to API communication and dashboard visualization — was also tested.

Initial feedback from a medical doctor was positive regarding the idea and the interface.

An important limitation raised during the feedback was that the reliability of the analysis depends on the amount and quality of laboratory information available for each patient.

Different medical users may also require different levels of information.

For example:

- Emergency-room staff may prefer a quick overview of the patient's condition and the most important alerts.
- Other healthcare professionals may want to explore detailed laboratory results, trends, and risk factors.

The current evaluation should be considered a **technical and academic evaluation**, not a clinical validation.

---

# 🚀 Running the Project

## Requirements

Before running LabTrend, make sure you have:

- Python 3
- Node.js
- npm
- Git

---

## 1. Clone the Repository

```bash
git clone <REPOSITORY-URL>
cd 2026_5_labtrend/deterioration-detector
```

Replace `<REPOSITORY-URL>` with the final GitHub repository URL.

---

## 2. Backend — Terminal 1

Move into the backend folder:

```bash
cd deterioration-detector
```

Create a Python virtual environment:

```bash
py -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

If `py` is not recognized, use:

```bash
python -m venv .venv
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Build the database:

```bash
python scripts/build_db.py
```

Build the risk data:

```bash
python scripts/build_risk.py
```

Start the FastAPI backend:

```bash
uvicorn src.api.main:app --reload --port 8000
```

The backend will be available at:

```text
http://localhost:8000
```

Leave this terminal running.

---

## 3. Frontend — Terminal 2

Open another terminal.

Move to the frontend directory:

```bash
cd deterioration-detector/frontend
```

Install frontend dependencies:

```bash
npm install
```

Start the Vite development server:

```bash
npm run dev
```

The frontend will normally be available at:

```text
http://localhost:5173
```

Open this address in your browser.

---

# ☁️ Data & Deployment

## Local Data

When running locally, DuckDB can be used to store and query the processed laboratory data.

## MotherDuck

MotherDuck provides cloud-hosted DuckDB storage and can be used for the larger processed dataset.

## Docker

The project can be packaged using Docker so that the frontend and backend can be deployed together.

## Render

The deployed version of LabTrend is hosted using Render.

---

# 📖 User Manual

A complete **LabTrend User Manual** is available separately.

The manual includes:

- System requirements
- Installation instructions
- Backend setup
- Frontend setup
- Instructions for running the system
- Required inputs
- Main user workflow
- Description of system outputs
- Explanation of the main features
- Interface screenshots
- Dashboard screenshots
- Patient Monitoring
- Early Warning
- Detector Accuracy
- Scoring Rule Book
- Pattern Builder
- Dataset Assistant

### 📥 Download the User Manual

**[Download LabTrend User Manual](https://drive.google.com/uc?export=download&id=1afWsu6GJUGGy7OMCGq5ov4ZuRHdxTqvh)**

---

# 👥 Team

## Group 5 — Seminar Project 2026

- **Mohammad Hajuj**
- **Khalil Dabbah**
- **Riad Bkheet**
- **Salwa Khaldi**
- **Naief Hajuj**
- **Mohammad Majdoub**

---

# 🔗 Project Links

### 🌐 Seminar Website

[LabTrend Seminar Website](https://sites.google.com/view/2026group5labtrend)

### 📖 User Manual

[Download LabTrend User Manual](https://drive.google.com/uc?export=download&id=1afWsu6GJUGGy7OMCGq5ov4ZuRHdxTqvh)

### 🚀 Live Application

[Open LabTrend](https://deterioration-detector.onrender.com/)

---

# ⚠️ Disclaimer

It is **not a medical device**, clinical diagnostic system, or approved clinical decision-support tool.

The system has not been clinically validated or approved by a medical regulatory authority.
