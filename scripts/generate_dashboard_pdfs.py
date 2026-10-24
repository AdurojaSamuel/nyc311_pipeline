#!/usr/bin/env python3
"""Generate one operating guide PDF for each NYC 311 dashboard."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "dashboard-guides"
NAVY = colors.HexColor("#17324d")
CYAN = colors.HexColor("#0c7c86")
MUTED = colors.HexColor("#536475")
PALE = colors.HexColor("#eef4f7")
AMBER = colors.HexColor("#fff2d8")
RED = colors.HexColor("#fce9e7")
PAGE_WIDTH = letter[0] - 1.35 * inch

GUIDES = [
    {
        "filename": "python-volume-dashboard.pdf",
        "title": "NYC 311 / Volume Lab",
        "subtitle": "Python Dash - monthly requests, forecasting, and workforce-cost planning",
        "facts": [
            ("Local URL", "http://localhost:8050/"),
            ("Launch", ".venv/bin/python src/app.py"),
            ("Primary source", "Curated Parquet lake plus a live recent NYC Open Data refresh"),
            ("Main audience", "Analysts and supervisors exploring monthly service-request trends"),
        ],
        "sections": [
            (
                "1. Purpose and page layout",
                [
                    "The Python Dash application is the monthly analytics and planning dashboard. It lets an analyst compare opened and closed request history, select a borough and analysis window, create a monthly forecast, and estimate monthly call-taker labor cost from configurable assumptions.",
                    "The screen has a borough/date filter area, summary indicators, opened-versus-closed history, a forecast section with model and horizon selectors, and a workforce planning view. Charts respond to the corresponding view or optimization action; model and borough choices can differ between the trend and forecast sections.",
                ],
                [],
            ),
            (
                "2. Start-up, data, and refresh",
                [
                    "Run the command in the quick-start panel from the repository root. The application reads the curated Parquet partitions for unique_key, created_date, closed_date, and borough, removes invalid creation dates and duplicate request identifiers, and prepares the dashboard's in-memory frame.",
                    "At startup, the app refreshes the recent opened/closed daily aggregates from the public NYC Open Data 311 dataset. The page footer reports the latest request date used. A successful refresh updates the in-memory dashboard data; the Parquet cache is not rewritten by the dashboard. A network or source error is surfaced during startup rather than silently relabeling stale data as live.",
                    "The source records are service requests, not call-center ACD arrivals, agent timecards, or labor expenditure. Monthly call forecasts and staff costs are planning estimates; calibrate assumptions using operational call-center data before making staffing decisions.",
                ],
                [
                    "Set NYC311_DATA_ROOT if the dashboard_data.parquet file or curated lake is stored outside the repository.",
                    "The checked-in daily cache is documented as current through 2026-10-23; a later live refresh may extend the in-memory data.",
                    "The app uses monthly aggregates and fills missing calendar months with zero when constructing a forecast series.",
                ],
            ),
            (
                "3. Trend analysis",
                [
                    "Choose a borough and a date range to inspect opened and closed request counts. The opened series is grouped by creation date; the closed series is grouped by closure date. The two series therefore describe separate lifecycle events and should not be interpreted as a same-cohort completion rate.",
                    "The chart is built from daily totals re-aggregated to calendar months. Filtering is applied to the request borough; missing borough labels are represented as Unknown. The monthly display is intended to reveal seasonality, long-run movement, and large changes, not individual case histories.",
                ],
                [],
            ),
            (
                "4. Forecast models and model selection",
                [
                    "Available model choices are Best, Holt-Winters, AutoARIMA, and LSTM. The backend requires at least 24 monthly observations for model selection. It reserves a chronological holdout of up to 12 months, evaluates candidates with mean absolute error (MAE), then fits the selected candidate to the full series for the requested horizon.",
                    "Holt-Winters uses additive trend and, when enough data exists, annual seasonality. AutoARIMA uses pmdarima automatic order selection with annual seasonality where supported. LSTM is a PyTorch one-variable recurrent model trained on normalized recent monthly values. Negative point forecasts are clipped to zero. Approximate uncertainty bounds widen with forecast horizon; they are not formal calibrated prediction intervals.",
                    "Best chooses the candidate with lowest holdout MAE among successfully fitted candidates. Failures are logged and recorded in MLflow; if every candidate fails, the backend raises an error. The result reports the selected model, holdout MAE, and MLflow run identifier.",
                ],
                [
                    "For a model-specific result, select that model and press its view action.",
                    "Use longer horizons as exploratory projections; forecast uncertainty and structural change increase with lead time.",
                    "Compare holdout errors as model diagnostics, not as a guarantee of future accuracy.",
                ],
            ),
            (
                "5. Workforce and labor-cost estimate",
                [
                    "The workforce panel turns a selected monthly opened-request forecast into an estimated monthly call volume using the calls-per-request assumption. It estimates required call takers with Erlang-C service-level calculations, applies an occupancy ceiling and paid-shrinkage assumption, and estimates labor spend from wage, operating hours, and business days.",
                    "The displayed comparison is forecast-driven staffing versus a fixed-staff baseline equal to peak staffing across the forecast horizon. The difference is a modeled savings estimate. It does not account for intraday call arrival distributions, shift overlap, breaks, skill groups, labor contracts, queue abandonment, or payroll rules.",
                    "Editable assumptions include call conversion, average handle time, forecast horizon, hourly wage, shrinkage, daily operating hours, monthly business days, service-level target, answer-time target, occupancy ceiling, borough, and forecast model. Values are scenario inputs, not measured NYC 311 staffing facts.",
                ],
                [],
            ),
            (
                "6. Interpretation, limitations, and troubleshooting",
                [
                    "Treat the charts as decision support. Validate the latest-data date, selected borough, forecast model, holdout error, and every labor assumption before comparing costs. Large or unexpected forecasts should trigger a source and aggregation review.",
                    "If the Parquet lake cannot be found, configure NYC311_DATA_ROOT and verify the curated partition paths. If refresh fails, confirm network access to data.cityofnewyork.us and retry. If model fitting fails, inspect the server log and MLflow run record; a short or irregular history may not support every model.",
                    "MLflow writes forecast candidate and best-fit runs to the configured tracking store. The default is a local SQLite store under ~/.nyc311_pipeline. See the repository README for tracking URI and artifact-store configuration.",
                ],
                [],
            ),
        ],
    },
    {
        "filename": "r-shiny-volume-dashboard.pdf",
        "title": "NYC 311 / R Shiny Dashboard",
        "subtitle": "Opened and closed trends, shared model forecasts, and monthly staffing estimates",
        "facts": [
            ("Local URL", "http://localhost:3838/"),
            ("Launch", "Rscript src/app.R"),
            ("Runtime", "Shiny + Plotly + Reticulate + configured Python environment"),
            (
                "Main audience",
                "R users and supervisors reviewing monthly trends and cost scenarios",
            ),
        ],
        "sections": [
            (
                "1. Purpose and page layout",
                [
                    "The R Shiny application provides a second interface to the monthly NYC 311 analytics workflow. Its trend panel displays opened or closed requests by date and borough. Its forecast panel projects monthly request volume using the same Python forecasting backend used by the Python Dash app. A third panel estimates call-taker needs and labor costs.",
                    "The page is organized into a trend view, monthly forecast view, and staffing optimization view. Each section has its own data or model controls and an action button. The bottom footer identifies the latest request date loaded at startup.",
                ],
                [],
            ),
            (
                "2. Start-up and environment",
                [
                    "Launch from the repository root with Rscript src/app.R. The app listens on port 3838 by default and binds to 0.0.0.0. Set SHINY_PORT or SHINY_HOST to change those values. The application requires Shiny, Plotly, and Reticulate.",
                    "Reticulate selects the Python executable in NYC311_PYTHON, then RETICULATE_PYTHON, then the repository .venv/bin/python, with python3 as a final executable lookup. The chosen environment must have the project's Python requirements installed, including pandas, PyArrow, forecasting libraries, and MLflow.",
                    "NYC311_DATA_ROOT points to the data root containing dashboard_data.parquet. The app reads that Parquet data through Python, then calls the shared Python data refresh and forecasting functions. A live refresh failure prevents the app from falsely presenting stale data as current.",
                ],
                [
                    "Check the selected Python interpreter with NYC311_PYTHON if Reticulate reports import or package errors.",
                    "Confirm the Parquet path and read permissions when start-up stops with a missing data error.",
                    "The footer's current-through date reflects the refreshed request data loaded for this session.",
                ],
            ),
            (
                "3. Opened and closed request history",
                [
                    "Choose OpenedSR or ClosedSR and a borough, then press the view action. Opened records are grouped by created date; closed records are grouped by close date. Borough filtering is applied before the time series is drawn.",
                    "Missing dates in the monthly forecast series are filled with zero. The history plot is daily and interactive; the forecast input is monthly. Opened and closed totals are not a matched cohort analysis and should not be interpreted as a service-level measure.",
                ],
                [],
            ),
            (
                "4. Forecasts and MLflow tracking",
                [
                    "The forecast controls select the target data type, borough, number of forecast months, and one of Best, Holt-Winters, AutoARIMA, or LSTM. These choices call the shared src/forecasting.py backend, so model requirements and output semantics are consistent with the Python Dash application.",
                    "Best compares candidates on a chronological holdout using MAE, selects the lowest-error successful model, refits it using the full history, and returns a point forecast and widening approximate bounds. Candidate scores, model parameters, and selected run metadata are tracked in MLflow. The app displays the chosen model, holdout MAE, and run ID.",
                    "At least 24 monthly observations are required for automatic model selection. Individual model failures are logged; if no candidate can be evaluated, the forecast action reports an error rather than inventing an estimate.",
                ],
                [],
            ),
            (
                "5. Staffing and labor-cost planning",
                [
                    "Press Optimize staffing to forecast opened requests for the selected borough and horizon, convert those requests to a call scenario, and calculate staffing for each projected month. The Erlang-C engine finds a headcount satisfying the entered service-level and occupancy targets while accounting for shrinkage. Costs use hourly wage, hours per operating day, and workdays per month.",
                    "The chart compares estimated forecast-driven labor cost with staffing fixed at the peak projected headcount. The summary reports the recommended call-taker range, minimum modeled service level, peak occupancy, total modeled savings, holdout MAE, and MLflow run ID.",
                    "The monthly staffing calculation does not solve a shift schedule. It abstracts demand across configured operating hours and cannot directly represent hourly arrival peaks, breaks, agent availability, skills, queue state, overtime, or contractual scheduling rules.",
                ],
                [
                    "Update calls per request, handle time, shrinkage, wage, work hours, workdays, service target, answer time, and occupancy from verified operations data.",
                    "A high monthly headcount or savings figure is not evidence of an operationally feasible roster.",
                ],
            ),
            (
                "6. Data meaning and support",
                [
                    "NYC Open Data's 311 dataset contains service-request activity, not call-center ACD traffic or workforce records. Any call conversion and staffing assumptions are illustrative planning parameters until calibrated against appropriate operational systems.",
                    "For Parquet, data refresh, model, or tracking errors, review the R console and Python logs. Confirm required R packages, Python interpreter, dataset access, NYC Open Data availability, and MLflow write permissions. The repository README documents the shared model and tracking configuration.",
                ],
                [],
            ),
        ],
    },
    {
        "filename": "hourly-staffing-optimizer.pdf",
        "title": "NYC311 Hourly Workforce Optimization",
        "subtitle": "Hourly demand proxy, shift assignments, budget constraints, and service shortfalls",
        "facts": [
            ("Local URL", "http://localhost:8051/"),
            ("Launch", ".venv/bin/python src/workforce_app.py"),
            ("Source", "Live NYC Open Data aggregates by request date, hour, and borough"),
            ("Optimizer", "Two-stage SciPy HiGHS mixed-integer linear program"),
        ],
        "sections": [
            (
                "1. Purpose and safe interpretation",
                [
                    "This standalone Dash application creates a next-day hourly staffing scenario. It forecasts hourly NYC 311 service-request creation, converts that request proxy to a configurable call-demand scenario, allocates agents to eligible shifts, and reports expected coverage and spend.",
                    "The source dataset does not contain ACD call arrivals, agent rosters, average handle-time records, skills, breaks, wages, or labor contracts. Forecast calls, available headcount, hourly wage, shift eligibility, and capacity assumptions are therefore scenario inputs. Do not treat an output as an approved production schedule.",
                ],
                [
                    "The default calls-per-request factor is 0.05; replace it with a factor validated against call-center telemetry.",
                    "Call allocations are same-hour planning estimates, not a queue or backlog simulation.",
                    "A roster upload can describe eligible shifts and agent-specific limits, but not all workforce policies.",
                ],
            ),
            (
                "2. Data loading and hourly forecast",
                [
                    "On launch, the app queries up to 120 recent days from the NYC Open Data 311 endpoint, grouped by day, hour, and borough. The page reports the most recent source date. Refresh live request data to replace the in-browser hourly data store with a fresh aggregate.",
                    "For each target hour, the forecast uses the average of recent observations at the same hour and weekday, with an eight-week lookback. The rolling-origin validation evaluates recent held-out dates and reports MAE and RMSE after scaling to the chosen calls-per-request scenario.",
                    "This is an interpretable seasonal baseline, not AutoARIMA, Holt-Winters, LSTM, or an uncertainty-calibrated demand model. Borough selection filters the history before forecasting. The selected target date must be later than the latest observed date for that borough.",
                ],
                [],
            ),
            (
                "3. Scenario controls",
                [
                    "Select a borough and target forecast date. Set calls per service request, available agents, eligible shift starts, shift duration, daily budget, hourly wage, average handle time, safe occupancy ceiling, maximum per-shift workload, and optional minimum per-shift workload. An optional CSV roster replaces the interchangeable-agent pool.",
                    "The roster requires agent_id, eligible_shifts, hourly_wage, and max_calls_per_shift; min_calls_per_shift is optional. eligible_shifts is a comma-separated list of start hours. Each agent can receive at most one eligible shift. Malformed files and invalid bounds produce explicit validation errors.",
                    "The model uses hourly capacity equal to 60 divided by average handle time, multiplied by the occupancy ceiling. A half-capacity midpoint hour approximates a break. Without a roster, all agents share the same wage, shift eligibility, and workload limits.",
                ],
                [
                    "Minimum per-shift calls is zero by default. A positive value may be infeasible when demand is low and should only be enabled when justified.",
                    "Shifts must fit within the modeled 24-hour day; the standard starts are 00:00, 04:00, 08:00, 12:00, and 16:00.",
                    "An hourly per-agent capacity is needed to protect service and workload; a per-shift cap alone is insufficient.",
                ],
            ),
            (
                "4. Optimization logic and outputs",
                [
                    "The SciPy HiGHS MILP has binary agent/shift choices, integer calls assigned to each agent/hour, and integer unserved demand. It enforces exact hourly demand balance, hourly on-duty capacity, per-shift maximum and optional minimum calls, one shift per agent, and a hard total labor budget.",
                    "Optimization is lexicographic: first minimize total same-hour unserved calls; then, without allowing worse service, minimize the cost of complete shifts. A budget-constrained shortfall is reported rather than hidden by overloading agents. Shift costs equal hourly wage multiplied by the complete shift length.",
                    "The chart shows forecast calls, calls assigned, uncovered calls, and scheduled agents. KPI cards show selected shifts, spend, remaining budget, solver status, and unmet demand. The schedule table presents agent/shift assignments and the hourly detail table reports each hour's capacity and service shortfall.",
                ],
                [],
            ),
            (
                "5. Running a scenario and diagnosing issues",
                [
                    "Press Forecast and optimize after reviewing all controls. The output includes rolling-origin error metrics and the configured request-to-call factor. A selected roster is used for the current browser session only; the app does not publish or persist an approved roster.",
                    "If no shifts are affordable, lower demand assumptions only when supported by evidence, increase the authorized budget, expand availability, or arrange overflow handling. Never relax safe capacity or contractual limits solely to suppress an alert.",
                    "If live data fails, verify network access to data.cityofnewyork.us and retry. If no borough data exists, choose another borough or ALL. If the solver cannot find a feasible result, inspect its error and confirm budget, roster, shift starts, minimum/maximum workload, and agent availability.",
                ],
                [],
            ),
            (
                "6. Important production gaps",
                [
                    "Before deployment, incorporate actual ACD arrival data, intraday seasonality and forecast error buffers, handling-time distributions, skills, breaks and rest rules, cross-midnight shifts, agent availability, contracts, schedule lock-in, queue/backlog carryover, abandonment, and service-level requirements.",
                    "The current model uses a single-day horizon and treats unserved calls as a same-hour service shortfall. It does not model queue carryover, dynamically re-optimize live arrivals, authenticate users, audit approvals, or write a published schedule.",
                ],
                [],
            ),
        ],
    },
    {
        "filename": "workforce-control-dashboard.pdf",
        "title": "NYC311 Workforce Control",
        "subtitle": "Supervisor-facing daily plan, safe capacity chart, release checks, and JSON export",
        "facts": [
            ("Local URL", "http://localhost:8052/"),
            ("Launch", ".venv/bin/python src/workforce_control_app.py"),
            ("Source", "Current public service-request aggregates; not call-center ACD data"),
            ("Plan export", "JSON download named nyc311-staffing-<plan-date>.json"),
        ],
        "sections": [
            (
                "1. Purpose and page structure",
                [
                    "Workforce Control is a separate supervisor-oriented daily planning dashboard inspired by the supplied site extraction. It presents source freshness, plan date and status, a conditional risk alert, forecast and staffing KPIs, an hourly coverage chart, operating controls, a recommended shift table, data/safety checks, and a downloadable JSON scenario.",
                    "The interface uses the reference's dark operations palette and compact status cards. It does not reproduce the reference's September 2026 simulated snapshot or its browser-side greedy calculation. It uses the current NYC Open Data hourly aggregate and the repository's server-side mixed-integer optimizer.",
                    "All exported staffing labels and metrics are planning scenarios. The current public source measures service requests, not call arrivals or agent work. The page labels this distinction and asks supervisors to calibrate the request-to-call factor from operational data.",
                ],
                [],
            ),
            (
                "2. Start-up, source, and forecast",
                [
                    "Start the app from the repository root. It loads 120 days of hourly NYC 311 service-request counts from the public Socrata endpoint, grouped by date, hour, and borough. The header shows the latest source date. Refresh live request data to replace the browser-held data; refresh failures are shown rather than ignored.",
                    "The forecast aggregates the most recent 56 days, matches historical weekdays to the selected plan date, and calculates the 75th percentile independently for each hour. It uses at least four matching weekdays. The resulting request proxy is scaled by the editable calls-per-request scenario factor; the default is 0.05.",
                    "A 28-day rolling-origin validation window reports MAE and RMSE in scenario calls per hour. These values describe the historical backtest of the same weekday/hour percentile method; they are not a production service-level guarantee.",
                ],
                [
                    "Default plan date is at least tomorrow in America/New_York and after the latest source date.",
                    "The borough menu includes ALL and the borough categories available in the NYC 311 source.",
                    "The 75th percentile is a conservative scenario input, not a calibrated probability interval.",
                ],
            ),
            (
                "3. Scenario inputs",
                [
                    "Daily labor budget ranges from $5,000 to $25,000 in $250 increments. The hourly per-agent capacity control ranges from 4 to 12. Demand buffer ranges from 100% to 130%. Per-agent shift maximum ranges from 32 to 72 calls in steps of two; the optional minimum is disabled at zero and ranges up to 32.",
                    "Additional inputs are plan date, borough, calls-per-request factor, available agent count, and hourly wage. Shifts are modeled as eight hours and may start at 00:00, 04:00, 08:00, 12:00, or 16:00. A midpoint hour is modeled at half capacity to represent a simplified break.",
                    "The initial scenario uses a $15,500 budget, eight calls per agent-hour, a 112% buffer, a 52-call per-shift maximum, no minimum workload, 0.05 calls per service request, 35 interchangeable agents, and $31.50 per paid hour. Every assumption is visible in the JSON export. The available-agent pool and hourly wage are not supplied by the public 311 dataset; populate those values from authorized workforce and payroll records before evaluating an operational proposal.",
                ],
                [],
            ),
            (
                "4. Optimization, status, and visual outputs",
                [
                    "The scenario applies the demand buffer, then passes the buffered hourly vector to the existing SciPy HiGHS MILP. The model minimizes uncovered hourly demand first and complete-shift labor cost second, subject to the hard budget, hourly capacity, per-shift workload limits, one shift per agent, and available staffing.",
                    "The chart compares the unbuffered call scenario and buffered demand to effective scheduled capacity after modeled breaks, and marks uncovered buffered calls. The peak note reports the peak forecast service-request proxy and rolling validation metrics.",
                    "Summary cards show forecast service-request volume, selected shifts, modeled spend, remaining budget, uncovered demand, and coverage percentage. Shift rows group selected agents by start time and show agent count, assigned calls, average calls per agent, and a Balanced, Near cap, or Light badge.",
                    "Ready for review is displayed only when no demand remains uncovered and the solver reports optimality. Otherwise the dashboard marks the plan Action required and surfaces the modeled shortfall or solver state. A feasible result is not an approval or a guarantee of real-world coverage.",
                ],
                [],
            ),
            (
                "5. Review and export workflow",
                [
                    "Confirm the source date and borough; adjust the demand conversion, buffer, availability, wage, and safe capacity assumptions; then select Calculate scenario. Review validation error, peak hour, coverage, spend, remaining budget, shift loads, and solver status before downloading the JSON plan.",
                    "The export contains generated time, source description and date, plan date, borough, all scenario inputs, summary metrics, hourly forecast/capacity/shortfall rows, shift totals, and validation metrics. It is a downloadable scenario artifact only. The dashboard does not persist, approve, audit, authenticate, or publish schedules.",
                    "If uncovered demand remains, consider an authorized budget increase, verified additional availability, or an approved overflow path. Do not exceed safe workloads, contractual limits, or break rules to eliminate a warning.",
                ],
                [],
            ),
            (
                "6. Limitations and production readiness",
                [
                    "Service requests and phone calls are distinct event types. The model has no live queue balance, abandonment, service-level target, agent skills, actual breaks, contractual rest or overtime rules, cross-midnight shifts, or locked-in assignments. The single-day shortfall metric means modeled demand not allocated in the same hour; it is not a measure of calls lost.",
                    "Before operational use, replace the proxy with validated ACD arrivals, estimate handling and occupancy from telemetry, construct truly feasible individual shifts, represent breaks and labor rules, include forecast uncertainty and queue dynamics, and obtain supervisor approval. Add access control, audit logging, schedule persistence, monitoring, and recovery before any production release.",
                    "The local Dash development server is for evaluation only. Use a production WSGI deployment and appropriate access controls if this prototype is hosted beyond a trusted local environment.",
                ],
                [],
            ),
        ],
    },
]


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "GuideTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=31,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "GuideSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=17,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=15,
        ),
        "section": ParagraphStyle(
            "GuideSection",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "GuideBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#1f2933"),
            spaceAfter=7,
        ),
        "bullet": ParagraphStyle(
            "GuideBullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=13,
            leftIndent=14,
            firstLineIndent=-9,
            textColor=colors.HexColor("#1f2933"),
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "GuideSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=MUTED,
        ),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(text).replace("\n", "<br/>"), style)


def _page_chrome(title: str):
    def draw(canvas, document):
        canvas.saveState()
        width, height = letter
        if document.page > 1:
            canvas.setStrokeColor(colors.HexColor("#d8e1e8"))
            canvas.line(
                document.leftMargin,
                height - 0.48 * inch,
                width - document.rightMargin,
                height - 0.48 * inch,
            )
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(MUTED)
            canvas.drawString(document.leftMargin, height - 0.38 * inch, title)
        canvas.setStrokeColor(colors.HexColor("#d8e1e8"))
        canvas.line(document.leftMargin, 0.48 * inch, width - document.rightMargin, 0.48 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            document.leftMargin, 0.32 * inch, "NYC 311 analytics - dashboard operating guide"
        )
        canvas.drawRightString(width - document.rightMargin, 0.32 * inch, f"Page {document.page}")
        canvas.restoreState()

    return draw


def generate_guide(guide: dict) -> Path:
    styles = _styles()
    destination = OUTPUT_DIR / guide["filename"]
    document = SimpleDocTemplate(
        str(destination),
        pagesize=letter,
        rightMargin=0.68 * inch,
        leftMargin=0.68 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.7 * inch,
        title=guide["title"],
        author="NYC 311 Analytics Project",
        subject=guide["subtitle"],
    )
    story = [
        Spacer(1, 0.25 * inch),
        _paragraph("DASHBOARD OPERATING GUIDE", styles["small"]),
        Spacer(1, 0.12 * inch),
        _paragraph(guide["title"], styles["title"]),
        _paragraph(guide["subtitle"], styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=CYAN, spaceAfter=13),
        _paragraph(
            "Prepared "
            + date.today().isoformat()
            + " | Detailed user, data, model, and operational reference",
            styles["small"],
        ),
        Spacer(1, 12),
    ]
    fact_rows = [
        [
            Paragraph(f"<b>{html.escape(key)}</b>", styles["small"]),
            _paragraph(value, styles["body"]),
        ]
        for key, value in guide["facts"]
    ]
    facts = Table(fact_rows, colWidths=[1.25 * inch, PAGE_WIDTH - 1.25 * inch], hAlign="LEFT")
    facts.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5e0e8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d5e0e8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            facts,
            Spacer(1, 12),
            _paragraph("Important data and decision boundary", styles["section"]),
        ]
    )
    warning = (
        "NYC 311 service-request records are not equivalent to phone-call arrivals, agent schedules, "
        "or payroll. Forecast conversions and labor inputs are scenarios unless calibrated against "
        "authorized operational records. Dashboard output is planning support and requires human review."
    )
    warning_table = Table(
        [[_paragraph(warning, styles["body"])]],
        colWidths=[PAGE_WIDTH],
    )
    warning_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), AMBER),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#e8c782")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([warning_table, Spacer(1, 8)])

    for heading, paragraphs, bullets in guide["sections"]:
        section_story = [_paragraph(heading, styles["section"])]
        section_story.extend(_paragraph(text, styles["body"]) for text in paragraphs)
        section_story.extend(_paragraph(f"- {text}", styles["bullet"]) for text in bullets)
        story.append(KeepTogether(section_story[:2]))
        story.extend(section_story[2:])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    document.build(
        story, onFirstPage=_page_chrome(guide["title"]), onLaterPages=_page_chrome(guide["title"])
    )
    return destination


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for guide in GUIDES:
        path = generate_guide(guide)
        print(f"Generated {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
