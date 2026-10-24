# NYC 311 Call Center Analytics & Workforce Optimization Platform

## Applications

The repository currently provides four interactive applications. The monthly dashboards read the curated Parquet lake and aggregate requests before plotting, while the hourly workforce apps query source-level aggregates; none load the full raw dataset into application memory.

### Python Dash

```bash
source .venv/bin/activate
python src/app.py
```

Open `http://127.0.0.1:8050`.

The Dash application provides separate opened and closed request views, borough filtering, real Holt-Winters, automatic ARIMA/SARIMA, and trained PyTorch LSTM forecasts, forecast intervals, and independent `view` buttons. Selecting **Best** compares the models on a chronological holdout and forecasts with the lowest-MAE model. The same model backend is used by both dashboards.

### R Shiny

The R implementation provides the same forecasts and call-taker staffing analysis through the shared Python model backend:

```bash
Rscript src/app.R
```

Open `http://127.0.0.1:3838`. The R app uses Shiny, Plotly, and Reticulate; it uses the configured Python environment's pandas/PyArrow to read Parquet and shares the Python forecasting backend. Set `NYC311_PYTHON` if the Python executable is not `.venv/bin/python`; the Python environment must install `requirements.txt`.

For either monthly application, set `NYC311_DATA_ROOT` when the data lake is outside the repository. The checked-in daily cache contains data from `2020-01-01` through `2026-10-23`; both monthly apps also refresh their recent window from NYC Open Data when they start.

Both existing dashboards refresh their recent opened/closed daily aggregates from NYC Open Data at startup and display the latest request date used by their forecasts. The checked-in Parquet file remains a local cache; network refresh errors are reported rather than silently represented as current live data.

### Hourly workforce optimization dashboard

Run the separate interactive hourly scenario app:

```bash
.venv/bin/python src/workforce_app.py
```

Open `http://127.0.0.1:8051`. The app fetches current NYC 311 creation timestamps aggregated by date/hour/borough from the public NYC Open Data endpoint. A recent same-weekday hourly baseline is evaluated with rolling-origin validation, then scaled by the editable calls-per-request assumption. This dataset contains service requests, not ACD call arrivals, agent timecards, or labor costs; the call conversion and staffing controls are scenario inputs and must be calibrated against real call-center data.

The allocation engine uses SciPy's HiGHS mixed-integer linear programming solver. It first minimizes same-hour unserved calls under the daily shift budget, then minimizes complete-shift labor cost without worsening that service result. The model includes one shift per agent, shift eligibility, half-hour midpoint break capacity, handle-time/occupancy-based hourly capacity, per-shift maximum/optional minimum workloads, and the daily budget. An optional CSV roster can supply per-agent eligible shifts and rates. See the dashboard notes for limitations around live queues, skills, contracts, and production scheduling.

### Supervisor workforce-control dashboard

Run a separate supervisor-oriented daily planning dashboard:

```bash
.venv/bin/python src/workforce_control_app.py
```

Open `http://127.0.0.1:8052`. The dark operations dashboard uses current hourly service-request aggregates, a 56-day same-weekday 75th-percentile forecast, rolling-origin validation, a configurable demand buffer, and the HiGHS MILP to show shift-level costs, safe hourly capacity, shortfalls, and a downloadable JSON scenario. Its request-to-call conversion, available agents, wage, and operating limits are assumptions, not values published by NYC Open Data. Exported schedules are planning artifacts for human review and are not automatically approved, saved, or published.

### Dashboard PDF guides

Detailed operating, data, model, and safety guides are provided separately for all four dashboards:

- [Python monthly Volume Lab](docs/dashboard-guides/python-volume-dashboard.pdf)
- [R Shiny monthly dashboard](docs/dashboard-guides/r-shiny-volume-dashboard.pdf)
- [Hourly workforce optimizer](docs/dashboard-guides/hourly-staffing-optimizer.pdf)
- [Supervisor Workforce Control](docs/dashboard-guides/workforce-control-dashboard.pdf)
- [Technical reference: Workforce Control and Hourly Staffing Optimizer](docs/dashboard-guides/workforce-optimization-technical-reference.pdf)

Regenerate the PDFs after changing dashboard behavior or documentation:

```bash
.venv/bin/python scripts/generate_dashboard_pdfs.py
```

Regenerate the combined workforce technical reference separately:

```bash
.venv/bin/python scripts/generate_workforce_technical_pdf.py
```

The PDF generator dependency is in `requirements-dev.txt` (`reportlab`); install development requirements with `pip install -r requirements-dev.txt`.

### Forecast tracking and model selection

The Python dependencies in `requirements.txt` include MLflow, PyTorch, and pmdarima. Each forecast request evaluates the selected model (or all three candidates) on the most recent chronological holdout, records MAE/RMSE and model metadata in the `nyc311-call-volume` MLflow experiment, and tags the selected best run. The default MLflow SQLite store is `~/.nyc311_pipeline/mlflow.db`, with artifacts in `~/.nyc311_pipeline/artifacts`; set `MLFLOW_TRACKING_URI` and optionally `MLFLOW_EXPERIMENT_NAME` to use a shared tracking server or another store. `MLFLOW_ARTIFACT_URI` can override the artifact destination for a new local experiment. Inspect the default store with `mlflow ui --backend-store-uri sqlite:///$HOME/.nyc311_pipeline/mlflow.db`.

### Call-taker workforce optimization

Both dashboards include a staffing scenario based on forecasted opened requests, converted to calls using an editable calls-per-request factor. Erlang-C estimates the minimum scheduled call-taker headcount meeting the chosen service-level target and occupancy ceiling; user-editable planning inputs include handle time, business hours/days, wage, and shrinkage. Monthly forecast-driven labor cost is compared with holding peak-horizon staffing fixed, with projected savings shown beside the cost chart. Initial defaults (one call per request, 8-minute handle time, 80% answered in 20 seconds, 85% occupancy, 30% shrinkage, 22 workdays, and $25/hour) are illustrative assumptions, not measured agency staffing data. Validate them against call-center telemetry, intraday arrival patterns, contracts, and scheduling rules before operational use.

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
- Monthly Holt-Winters, automatic ARIMA/SARIMA, and trained LSTM forecasts.
- Holdout-based best-model selection and MLflow run tracking.
- Erlang-C call-taker staffing estimates with adjustable assumptions and labor-cost comparisons.
- Plotly visualization with R-style two-panel controls.

### Technology

- R
- Shiny
- Plotly
- Arrow
- Reticulate and Python forecasting runtime

---

# 6. Python Dash Application

### Purpose

Provide a Python-based analytics interface.

### Current Features

- Daily opened and closed request history.
- Borough filtering.
- Monthly Holt-Winters, automatic ARIMA/SARIMA, and trained LSTM forecasts.
- Approximate forecast ranges and MLflow-tracked model selection.
- Erlang-C staffing recommendations and labor-cost savings scenarios.
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