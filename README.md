# NYC 311 Call Center Analytics & Workforce Optimization Platform

## Applications

The repository currently provides two interactive applications. Both read the curated Parquet lake and aggregate requests before plotting, so they do not load the full raw dataset into application memory.

### Python Dash

```bash
source .venv/bin/activate
python src/app.py
```

Open `http://127.0.0.1:8050`.

The Dash application provides separate opened and closed request views, borough filtering, monthly Holt-Winters, ARIMA, and LSTM-style forecasts, forecast confidence bands, and independent `view` buttons.

### R Shiny

The R implementation follows the original Shiny layout and behavior:

```bash
Rscript src/app.R
```

Open `http://127.0.0.1:5170`. The R app uses Shiny, Plotly, Forecast, Zoo, and Reticulate. Reticulate calls the Python environment's DuckDB package to aggregate the Parquet lake. Set `NYC311_PYTHON` if the Python executable is not `.venv/bin/python`.

For either application, set `NYC311_DATA_ROOT` when the data lake is outside the repository. The current local lake contains data from `2020-01-01` through `2026-08-25`.

### Research / Prototype Project

---

## 1. Project Overview

This project is a research and prototype initiative focused on building an end-to-end analytics, forecasting, optimization, and visualization platform using the **NYC 311 Service Requests dataset**.

The objective is to investigate how modern data engineering, time-series forecasting, machine learning, workforce optimization, and business intelligence techniques can be combined to improve call center operations and workforce planning.

The project runs on **Linux** and uses a locally managed **Parquet-based Data Lake** as the primary storage layer.

---

## 2. Research Objectives

The project seeks to answer the following questions:

### Forecasting

Can historical NYC 311 call/service request data be used to accurately forecast future daily call volumes?

### Workforce Optimization

Given a forecasted call volume:

- How many agents are required each day?
- How many agents are required each month?
- How should staffing levels be adjusted to maintain service levels?
- How can staffing costs be minimized while maintaining operational targets?

### Operational Analytics

How can call center managers monitor performance using modern dashboards and KPI visualizations?

---

# 3. High-Level Architecture

```text
+-------------------------+
| NYC Open Data API       |
| NYC 311 Dataset         |
+-----------+-------------+
            |
            v
+-------------------------+
| Python Data Pipeline    |
| Linux                   |
+-----------+-------------+
            |
            v
+-------------------------+
| Parquet Data Lake       |
| Local Storage           |
+-----------+-------------+
            |
            +----------------------+
            |                      |
            v                      v
+------------------+    +------------------+
| Forecast Models  |    | KPI Analytics    |
| ARIMA            |    | Power BI         |
| Holt-Winters     |    | Dashboards       |
| LSTM             |    +------------------+
+---------+--------+
          |
          v
+-------------------------+
| Workforce Optimization  |
| Staffing Recommendation |
+-----------+-------------+
            |
            +----------------------+
            |                      |
            v                      v
+------------------+    +------------------+
| R Shiny App      |    | Python Dash App  |
+------------------+    +------------------+
```

---

# 4. Project Phases

The project is organized into four sequential phases.

---

## Phase 1 — Data Engineering

### Objective

Build a robust Linux-based data pipeline capable of:

- Performing the initial historical load of NYC 311 data.
- Storing data efficiently in Parquet format.
- Maintaining a local analytical data lake.
- Performing daily incremental updates.
- Supporting future analytical workloads.

### Technology

- Python
- Requests
- Pandas
- PyArrow
- DuckDB
- Linux Cron/Systemd

### Deliverables

- Historical data extraction
- Incremental ingestion process
- Metadata tracking
- Data validation
- Data quality monitoring

---

## Phase 2 — Forecasting Engine

### Objective

Forecast daily call volume using multiple forecasting approaches.

The forecasting framework will compare traditional statistical models with deep learning methods.

### Models

#### Holt-Winters

Used for:

- Trend detection
- Seasonality modeling
- Baseline forecasting

#### ARIMA

Used for:

- Autoregressive behavior
- Time-series decomposition
- Statistical benchmarking

#### LSTM

Used for:

- Deep learning forecasting
- Complex temporal patterns
- Non-linear relationships

### Forecasting Output

Daily forecasted:

- Call volume
- Service requests
- Expected workload

### Model Evaluation

Models will be evaluated using:

- MAE
- RMSE
- MAPE
- Forecast Bias

### Deliverables

- Forecast comparison framework
- Daily forecast generation
- Model performance reports

---

## Phase 3 — Workforce Optimization

### Objective

Determine the optimal staffing level required to handle forecasted call demand.

The optimization engine will evolve through three progressively advanced scenarios.

---

### Scenario A

#### Volume-Based Staffing

**Input**

- Forecasted call volume

**Output**

- Recommended staffing level

**Goal**

Determine the minimum number of agents required based solely on expected workload.

---

### Scenario B

#### Service-Level Driven Staffing

**Input**

- Forecasted call volume
- Service-level targets

**Examples**

- Answer 80% of calls within 30 seconds
- Reduce customer waiting times

**Output**

- Staffing recommendations
- Service-level compliance estimates

**Goal**

Balance staffing costs with customer service expectations.

---

### Scenario C

#### Operational Workforce Optimization

**Input**

- Forecasted call volume
- Service-level requirements
- Agent productivity metrics
- Shift schedules
- Working-hour constraints

**Output**

- Daily staffing plans
- Monthly staffing plans
- Shift recommendations
- Capacity utilization metrics

**Goal**

Develop an operational decision-support tool for workforce planning.

---

## Optimization Techniques

Potential methods include:

### Queueing Theory

- Erlang C
- Waiting-time analysis
- Service-level estimation

### Mathematical Optimization

- Linear Programming
- Integer Programming
- Mixed Integer Programming

### Simulation

- Monte Carlo Simulation
- Scenario Analysis

---

## Phase 4 — Analytics & Visualization

### Objective

Provide multiple user interfaces for consuming forecasts and staffing recommendations.

---

# 5. R Shiny Application

### Purpose

Develop an interactive forecasting portal using R.

### Current Features

- Daily opened and closed request history.
- Borough filtering.
- Monthly Holt-Winters and ARIMA forecasts.
- LSTM-style seasonal forecast with a residual-based 95% confidence interval.
- Plotly visualization with R-style two-panel controls.

### Technology

- R
- Shiny
- Plotly
- Forecast
- Zoo
- Reticulate

---

# 6. Python Dash Application

### Purpose

Provide a Python-based analytics interface.

### Current Features

- Daily opened and closed request history.
- Borough filtering.
- Monthly Holt-Winters, ARIMA, and LSTM-style forecasts.
- Forecast confidence bands.
- DuckDB-backed aggregation of the curated Parquet lake.

### Technology

- Python
- Dash
- Plotly
- Pandas

---

# 7. Power BI Dashboard

### Objective

Create an executive call center dashboard.

### Data Sources

The dashboard will support:

### Option A

Direct connection to:

```text
Parquet Data Lake
```

### Option B

Connection through:

```text
DuckDB
```

Future versions may also support:

```text
PostgreSQL
```

---

## Power BI KPIs

### Volume Metrics

- Daily call volume
- Monthly call volume
- Requests by category
- Requests by borough

### Service Metrics

- Average response time
- Resolution time
- Open requests
- Closed requests

### Forecast Metrics

- Forecasted call volume
- Forecast accuracy
- Model comparison

### Workforce Metrics

- Required agents
- Staffing utilization
- Service-level achievement
- Capacity gap analysis

### Executive Metrics

- Trends
- Seasonality
- Operational performance
- Resource planning outlook

---

# 8. Repository Structure

```text
nyc311_pipeline/
│
├── config/                         # Pipeline configuration
├── data/
│   ├── staging/                    # Raw extraction batches
│   └── curated/                    # Partitioned Parquet lake
├── logs/                           # Pipeline logs
├── metadata/
│   ├── state.json                  # Incremental ingestion state
│   └── runs/                       # Run manifests and checkpoints
├── reports/                        # Generated project reports
├── scripts/
│   └── run_incremental_with_email.sh
├── src/
│   ├── app.py                      # Python Dash application
│   ├── app.R                       # R Shiny application
│   ├── nyc311_pipeline.py          # Ingestion and curation pipeline
│   └── *.ipynb                     # Analysis notebooks
├── requirements.txt                # Python dependencies
└── README.md
```

---

# 9. Expected Outcomes

Upon completion, the platform will provide:

1. Automated NYC 311 data ingestion.
2. Daily call volume forecasts using Holt-Winters, ARIMA, and LSTM.
3. Workforce optimization recommendations.
4. R Shiny forecasting dashboards.
5. Python Dash forecasting dashboards.
6. Executive Power BI dashboards.
7. A reusable research platform for call center analytics and workforce planning.

---

# 10. Disclaimer

This project is a research and prototype initiative intended to evaluate forecasting, optimization, and visualization techniques using publicly available NYC 311 data. Results should be validated before being used for operational staffing decisions in a production call center environment.