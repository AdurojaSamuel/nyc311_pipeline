#!/usr/bin/env python3
"""Generate the technical reference for the two hourly workforce dashboards."""

from __future__ import annotations

import html
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "dashboard-guides" / "workforce-optimization-technical-reference.pdf"
NAVY = colors.HexColor("#17324d")
CYAN = colors.HexColor("#0c7c86")
MUTED = colors.HexColor("#536475")
PALE = colors.HexColor("#eef4f7")
AMBER = colors.HexColor("#fff2d8")
RED = colors.HexColor("#fce9e7")
CONTENT_WIDTH = letter[0] - 1.3 * inch

styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="DocumentTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=29,
        textColor=NAVY,
        alignment=TA_CENTER,
        spaceAfter=9,
    )
)
styles.add(
    ParagraphStyle(
        name="Subtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=14,
    )
)
styles.add(
    ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=NAVY,
        spaceBefore=9,
        spaceAfter=7,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        name="SubHeading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=CYAN,
        spaceBefore=7,
        spaceAfter=4,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        name="BodyTextCustom",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12.4,
        textColor=colors.HexColor("#243746"),
        spaceAfter=6,
    )
)
styles.add(
    ParagraphStyle(
        name="BulletCustom",
        parent=styles["BodyTextCustom"],
        leftIndent=13,
        firstLineIndent=-8,
        bulletIndent=1,
        spaceAfter=3,
    )
)
styles.add(
    ParagraphStyle(
        name="Equation",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=8.2,
        leading=11.5,
        leftIndent=10,
        rightIndent=8,
        backColor=PALE,
        borderPadding=6,
        spaceBefore=3,
        spaceAfter=6,
    )
)
styles.add(
    ParagraphStyle(
        name="SmallNote",
        parent=styles["BodyTextCustom"],
        fontSize=8,
        leading=10.5,
        textColor=MUTED,
    )
)


def paragraph(text: str, style: str = "BodyTextCustom") -> Paragraph:
    return Paragraph(text, styles[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(f"- {text}", styles["BulletCustom"])


def equation(text: str) -> Paragraph:
    return Paragraph(html.escape(text).replace("\n", "<br/>"), styles["Equation"])


def make_table(
    headers: list[str],
    rows: list[list[str]],
    widths: list[float],
    *,
    font_size: float = 7.8,
    highlight: int | None = None,
) -> Table:
    body_style = ParagraphStyle(
        name=f"Table{font_size}{len(rows)}",
        parent=styles["BodyTextCustom"],
        fontSize=font_size,
        leading=font_size + 2.3,
        spaceAfter=0,
    )
    header_style = ParagraphStyle(
        name=f"TableHeader{font_size}{len(rows)}",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    data = [[Paragraph(html.escape(value), header_style) for value in headers]]
    data.extend([Paragraph(html.escape(value), body_style) for value in row] for row in rows)
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d5e0e8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
    ]
    if highlight is not None:
        commands.append(("BACKGROUND", (0, highlight), (-1, highlight), AMBER))
    table.setStyle(TableStyle(commands))
    return table


def page_chrome(canvas, document) -> None:
    canvas.saveState()
    width, height = letter
    canvas.setStrokeColor(colors.HexColor("#d5e0e8"))
    canvas.setLineWidth(0.5)
    canvas.line(0.65 * inch, height - 0.52 * inch, width - 0.65 * inch, height - 0.52 * inch)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(NAVY)
    canvas.drawString(
        0.65 * inch, height - 0.4 * inch, "NYC 311 | HOURLY WORKFORCE TECHNICAL REFERENCE"
    )
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.65 * inch, 0.38 * inch, "Implementation reference | 24 October 2026")
    canvas.drawRightString(width - 0.65 * inch, 0.38 * inch, f"Page {document.page}")
    canvas.restoreState()


def build_story() -> list:
    story = [
        Spacer(1, 0.18 * inch),
        paragraph("NYC 311 Workforce Optimization", "DocumentTitle"),
        paragraph(
            "Technical problem definition, mathematical formulation, solution method, "
            "and implementation notes for two hourly staffing dashboards",
            "Subtitle",
        ),
        make_table(
            ["Dashboard", "Application entry point", "Local URL"],
            [
                [
                    "Hourly Staffing Optimizer",
                    "src/workforce_app.py",
                    "http://127.0.0.1:8051/",
                ],
                [
                    "Supervisor Workforce Control",
                    "src/workforce_control_app.py",
                    "http://127.0.0.1:8052/",
                ],
            ],
            [2.1 * inch, 2.3 * inch, CONTENT_WIDTH - 4.4 * inch],
        ),
        Spacer(1, 10),
        paragraph("Executive summary", "SectionHeading"),
        paragraph(
            "Both applications turn recent, borough-filterable NYC 311 service-request "
            "creation aggregates into a 24-hour call-demand scenario, then solve a "
            "budget-constrained mixed-integer staffing problem. The optimizer assigns "
            "whole shifts, allocates integer calls to staffed agents by hour, respects "
            "hourly handling capacity and per-shift workload limits, and records calls "
            "that cannot be covered. Its objective is lexicographic: first minimize "
            "same-hour unserved demand; next minimize labor cost without increasing "
            "the best service shortfall found in the first stage.",
        ),
        paragraph(
            "<b>Critical interpretation:</b> NYC Open Data contains service requests, "
            "not call-center ACD arrivals, employee schedules, agent handling times, "
            "or payroll. Calls-per-request, staff availability, wage, and capacity "
            "controls are scenario inputs. Outputs are planning aids, not approved "
            "rosters or measured labor savings.",
        ),
        paragraph("1. Problem and decision context", "SectionHeading"),
        paragraph(
            "The planning problem is to match a forecast of hourly arrivals to a set "
            "of feasible shifts. A plan should cover as much demand as possible within "
            "the daily budget and safe workload assumptions, while identifying rather "
            "than concealing any service shortfall. The dashboards work at one-hour "
            "resolution for a single planning day. They do not simulate a live queue.",
        ),
        make_table(
            ["Element", "Model representation", "Interpretation"],
            [
                ["Demand", "D[t], t = 0,...,23", "Estimated calls arriving in each hour"],
                ["Assignment", "y[i,s] in {0,1}", "Agent i is assigned to candidate shift s"],
                ["Call allocation", "x[i,t] integer >= 0", "Calls assigned to agent i in hour t"],
                ["Shortfall", "u[t] integer >= 0", "Calls not assigned in hour t"],
                ["Cost", "c[i,s] * y[i,s]", "Cost of the complete assigned shift"],
            ],
            [1.15 * inch, 1.65 * inch, CONTENT_WIDTH - 2.8 * inch],
        ),
        paragraph(
            "For this model, unserved means not covered in the same hour. It is not "
            "automatically a lost call or a carry-over backlog. A queueing formulation "
            "would need state balance, abandonment, service levels, and arrivals during "
            "the interval.",
            "SmallNote",
        ),
        PageBreak(),
        paragraph("2. Data flow and demand forecasting", "SectionHeading"),
        paragraph(
            "Both apps use <b>nyc311_data.load_recent_hourly_requests</b>. At startup, "
            "the loader requests up to 120 recent days from the NYC Open Data "
            "Socrata resource <b>erm2-nwe9</b>, grouping at source by request creation "
            "date, hour, and borough. It normalizes missing borough values, sorts the "
            "aggregates, and reports the newest source date. Each dashboard also has a "
            "refresh action that reloads the grouped series; a refresh error is surfaced "
            "rather than silently being described as current.",
        ),
        equation(
            "Source aggregate: R[d,h,b] = count of requests created on date d, hour h, borough b."
        ),
        paragraph(
            "The selected borough is aggregated across borough labels for ALL, or "
            "filtered to one borough. A complete daily-by-hour matrix is built for "
            "forecasting, reindexed to 24 hours per date; missing date/hour combinations "
            "are filled with zero. Therefore, source completeness and the request "
            "timestamp definition matter to both forecast variants.",
        ),
        paragraph("2.1 Hourly Staffing Optimizer: same-weekday mean baseline", "SubHeading"),
        paragraph(
            "The baseline in <b>src/workforce_optimizer.py::forecast_hourly_demand</b> "
            "uses the mean of observations at each hour from the preceding 56 calendar "
            "days having the target date's weekday. At least 28 days of history are "
            "required, and a target date must be after the latest observation. The mean "
            "request count is rounded to a non-negative integer, then converted to calls "
            "using the editable factor (default 0.05 calls per request).",
        ),
        equation(
            "Rhat[t,h] = mean{ R[d,h] : t-56 days <= d < t, weekday(d)=weekday(t) }\n"
            "D[t,h] = max(0, round( Rhat[t,h] * q )),  q = calls per request",
        ),
        paragraph(
            "Rolling-origin validation uses past dates, never future observations for "
            "a validation prediction. The validation window is the later of the final "
            "28 observed dates or the first date with 56 days of history. For each "
            "validation date, the predictor uses only its preceding 56 days with the "
            "same weekday. The dashboard reports MAE and RMSE in scenario calls per "
            "hour, with the number of hourly observations.",
        ),
        paragraph(
            "2.2 Supervisor Workforce Control: weekday/hour upper-quantile baseline", "SubHeading"
        ),
        paragraph(
            "The supervisor app calls <b>src/workforce_control.py::forecast_control_demand</b>. "
            "For each hour, it selects the preceding 56 days with the target weekday "
            "and uses the 75th percentile (configurable internally within 0.50-0.99). "
            "At least four matching weekdays must exist. This is a deliberately "
            "more conservative baseline than a mean, not a learned time-series model.",
        ),
        equation(
            "Qhat[t,h] = quantile_0.75{ R[d,h] : t-56 days <= d < t, weekday(d)=weekday(t) }\n"
            "Rproxy[t,h] = max(0, round(Qhat[t,h]))\n"
            "Dbase[t,h] = max(0, round(Rproxy[t,h] * q))\n"
            "Dbuffer[t,h] = round(Dbase[t,h] * beta), 1.00 <= beta <= 1.30",
        ),
        paragraph(
            "This dashboard defaults to q=0.05 and beta=1.12. It validates against "
            "rolling-origin dates from the latest 28 calendar days, skipping dates "
            "without four prior matching weekdays. MAE and RMSE are calculated in "
            "calls per hour. The buffer is applied after the point forecast and before "
            "optimization; it is a scenario reserve, not a statistical prediction interval.",
        ),
        paragraph(
            "The two models should not be conflated: the Hourly Optimizer uses a same-weekday "
            "mean; Workforce Control uses a same-weekday 75th percentile plus an explicit "
            "demand buffer. Their recommended staffing and shortfalls can differ even "
            "with identical cost/capacity controls.",
        ),
        PageBreak(),
        paragraph("3. Mathematical formulation", "SectionHeading"),
        paragraph("Sets and inputs", "SubHeading"),
        make_table(
            ["Symbol", "Definition"],
            [
                ["T", "Hourly periods {0,...,23}."],
                [
                    "I",
                    "Available call takers; roster rows when supplied, otherwise interchangeable agents.",
                ],
                [
                    "S[i]",
                    "Feasible shift start times for agent i; shifts are wholly within the day.",
                ],
                ["D[t]", "Forecast or buffered call demand in hour t."],
                ["L", "Shift length in hours."],
                ["a[i,s,t]", "1 when shift s places agent i on duty in hour t; otherwise 0."],
                ["H", "Hourly call capacity at the configured handling time and occupancy."],
                ["c[i,s]", "Hourly wage for agent i multiplied by shift length."],
                [
                    "Cmin[i], Cmax[i]",
                    "Optional minimum and maximum total assigned calls for agent i's completed shift.",
                ],
                ["B", "Daily labor budget."],
            ],
            [1.35 * inch, CONTENT_WIDTH - 1.35 * inch],
        ),
        paragraph("Decision variables", "SubHeading"),
        equation(
            "y[i,s] in {0,1}     1 if agent i is assigned to shift s\n"
            "x[i,t] in Z+,       calls assigned to agent i during hour t\n"
            "u[t]   in Z+,       forecast calls not covered during hour t",
        ),
        paragraph("Lexicographic objective", "SubHeading"),
        paragraph(
            "The implementation solves two MILPs sequentially rather than relying on "
            "a hand-tuned big-M coefficient. Stage 1 finds the smallest total shortfall. "
            "Stage 2 minimizes full-shift cost subject to shortfall no worse than the "
            "Stage 1 result. This prioritizes modeled service coverage over cost while "
            "respecting the budget in both stages.",
        ),
        equation(
            "Stage 1: minimize   U = sum[t in T] u[t]\n"
            "Stage 2: minimize   C = sum[i in I] sum[s in S[i]] c[i,s] y[i,s]\n"
            "         subject to all constraints and sum[t in T] u[t] <= U*",
        ),
        paragraph("Constraints", "SubHeading"),
        equation(
            "(1) Demand balance, each hour:\n"
            "    sum[i in I] x[i,t] + u[t] = D[t]                         for all t\n"
            "(2) On-duty hourly capacity:\n"
            "    x[i,t] <= H[i,t] * sum[s in S[i]] a[i,s,t] y[i,s]       for all i,t\n"
            "(3) Per-shift maximum workload:\n"
            "    sum[t in T] x[i,t] <= Cmax[i] * sum[s in S[i]] y[i,s]   for all i\n"
            "(4) Optional per-shift minimum workload:\n"
            "    sum[t in T] x[i,t] >= Cmin[i] * sum[s in S[i]] y[i,s]   for all i\n"
            "(5) At most one shift per agent:\n"
            "    sum[s in S[i]] y[i,s] <= 1                             for all i\n"
            "(6) Daily budget:\n"
            "    sum[i,s] c[i,s] y[i,s] <= B",
        ),
        PageBreak(),
        paragraph("4. Capacity, cost, and solver implementation", "SectionHeading"),
        paragraph("Hourly capacity and midpoint break", "SubHeading"),
        paragraph(
            "In the Hourly Optimizer, hourly capacity is computed from average handle "
            "time and a configured occupancy ceiling: H = (60 / AHT_minutes) * occupancy_fraction. "
            "The default inputs are eight minutes and 85% occupancy, giving 6.375 "
            "calls per agent-hour before the model's integer allocations. In Workforce "
            "Control, the user directly sets maximum calls per agent-hour (default 8); "
            "the equivalent AHT/occupancy derivation is not applied there.",
        ),
        equation(
            "H[i,t] = H * b[i,s,t]\n"
            "b[i,s,t] = 0.5 when t = s + floor(L/2), otherwise 1.0, for an assigned shift\n"
            "x[i,t] <= H[i,t] * active[i,t]",
        ),
        paragraph(
            "The selected shift has one modeled midpoint hour at half capacity, intended "
            "as a simple proxy for a 30-minute break. It is not a detailed sub-hour break "
            "schedule and does not verify labor rules or rest compliance. If a shift "
            "starts at 16:00 and lasts eight hours, its end is 24:00; no cross-midnight "
            "shift is permitted.",
        ),
        paragraph("Shift cost and workload", "SubHeading"),
        equation(
            "c[i,s] = hourly_wage[i] * L\n"
            "C = sum of complete assigned-shift costs, not hourly headcount cost\n"
            "Cmin[i], Cmax[i] constrain total calls over the full shift, not each hour",
        ),
        paragraph(
            "When no roster is uploaded, the Hourly Optimizer creates the configured "
            "number of interchangeable agents with shared eligible starts, wage, and "
            "workload limits. Its optional CSV roster has agent_id, eligible_shifts, "
            "hourly_wage, and max_calls_per_shift; min_calls_per_shift is optional "
            "and defaults to zero. Agent shift eligibility and costs are then individual.",
        ),
        paragraph("Numerical solution procedure", "SubHeading"),
        make_table(
            ["Step", "Implementation"],
            [
                [
                    "1. Construct variables",
                    "Binary y for each feasible agent/start; integer x for each agent/hour and u for each hour.",
                ],
                [
                    "2. Build sparse constraints",
                    "SciPy sparse COO/CSR matrix and LinearConstraint encode demand, capacity, workloads, one shift, and budget.",
                ],
                [
                    "3. Minimize shortfall",
                    "scipy.optimize.milp with integer variables and unit objective coefficient on each u[t].",
                ],
                [
                    "4. Minimize cost",
                    "Second milp minimizes shift costs and constrains total u to be no more than the first-stage result.",
                ],
                [
                    "5. Report",
                    "Return hourly coverage/capacity, selected shifts and workloads, cost, budget remaining, shortfall, and solver status.",
                ],
            ],
            [1.45 * inch, CONTENT_WIDTH - 1.45 * inch],
        ),
        paragraph(
            "The solver is SciPy's HiGHS MILP backend. The implementation uses a "
            "30-second time limit and 1% relative MIP gap. If Stage 2 produces no "
            "solution vector, Stage 1's solution is retained. Consequently, always "
            "inspect the returned solver status; a time-limited incumbent is not proof "
            "of a globally optimal schedule.",
        ),
        PageBreak(),
        paragraph("5. Dashboard-specific implementation", "SectionHeading"),
        paragraph("5.1 Hourly Staffing Optimizer (port 8051)", "SubHeading"),
        paragraph(
            "Entry point: <b>src/workforce_app.py</b>. Forecasting, roster parsing, "
            "and optimization live in <b>src/workforce_optimizer.py</b>. The app loads "
            "120 recent days at startup and can refresh live grouped records. It accepts "
            "borough, target date, calls-per-request factor, available agents, eligible "
            "shift starts, shift length, daily budget, wage, average handle time, "
            "occupancy limit, per-shift max/min workload, and optional roster CSV.",
        ),
        make_table(
            ["Control / output", "Default or semantics"],
            [
                [
                    "Request-to-call factor",
                    "0.05; scenario conversion, not a measured NYC311 ratio.",
                ],
                [
                    "Generic agent pool",
                    "35 agents; shift starts 00, 04, 08, 12, 16; 8-hour shifts.",
                ],
                [
                    "Budget / wage",
                    "$5,500 daily budget; $25 per hour, unless roster rates are supplied.",
                ],
                [
                    "Capacity",
                    "8-minute handle time; 85% occupancy; one midpoint break at 50% capacity.",
                ],
                ["Per-shift calls", "Maximum 48; optional minimum defaults to 0."],
                [
                    "Results",
                    "Forecast validation, demand/served/shortfall/staffing chart, selected shifts, hourly table, spend, remaining budget, solver status.",
                ],
            ],
            [1.55 * inch, CONTENT_WIDTH - 1.55 * inch],
        ),
        paragraph("5.2 Supervisor Workforce Control (port 8052)", "SubHeading"),
        paragraph(
            "Entry point: <b>src/workforce_control_app.py</b>; forecast helper: "
            "<b>src/workforce_control.py</b>; MILP is shared with the Hourly Optimizer. "
            "Its forecast uses a 56-day same-weekday 75th percentile and then applies "
            "an editable 100%-130% demand buffer. Controls include target date, borough, "
            "budget, direct hourly cap, buffer, max/min shift calls, calls-per-request "
            "factor, available agents, and wage. The shift length is eight hours, "
            "starts are fixed at 00/04/08/12/16, and midpoint capacity is halved.",
        ),
        make_table(
            ["Control / output", "Default or semantics"],
            [
                ["Budget / wage", "$15,500 daily; $31.50 per hour."],
                ["Demand assumptions", "8 calls/agent-hour; 112% buffer; 0.05 calls/request."],
                ["Generic agent pool", "35 agents; five fixed eight-hour shift starts."],
                ["Per-shift calls", "Maximum 52; minimum 0 by default."],
                [
                    "Results",
                    "Request proxy, shifts, spend and remaining budget, uncovered buffered demand, coverage percentage, safe capacity chart, shift summary, validation, JSON export.",
                ],
                [
                    "Release treatment",
                    "Plan is marked ready for review only when solver status is optimal and no buffered demand is uncovered; export remains a review artifact.",
                ],
            ],
            [1.55 * inch, CONTENT_WIDTH - 1.55 * inch],
        ),
        paragraph(
            "The control app distinguishes baseline forecast calls from buffered calls "
            "sent to the optimizer. Its charts present baseline demand, buffered demand, "
            "staffed handling capacity, and uncovered buffered calls. The displayed "
            "shift table groups assignments by shift start; JSON export retains scenario "
            "configuration, hourly results, assignments, validation metrics, and source "
            "date.",
        ),
        PageBreak(),
        paragraph("6. Reading results and operational use", "SectionHeading"),
        make_table(
            ["Measure", "Definition / correct interpretation"],
            [
                [
                    "Forecast request proxy",
                    "Hourly service requests expected by the chosen statistical baseline; not ACD calls.",
                ],
                [
                    "Forecast calls",
                    "Rounded request proxy multiplied by calls-per-request scenario factor.",
                ],
                [
                    "Buffered calls",
                    "Workforce Control forecast calls multiplied by the selected reserve factor and rounded; only this enters that app's solver.",
                ],
                [
                    "Calls served / covered",
                    "Integer calls assigned to agents in each hour, constrained by shift and capacity.",
                ],
                [
                    "Unserved / uncovered",
                    "Same-hour unmet modeled demand; no carry-forward queue is included.",
                ],
                [
                    "Staffing spend",
                    "Sum of full costs for assigned shifts. It is not a payroll forecast unless wages and rules are calibrated.",
                ],
                ["Budget remaining", "Configured daily budget minus modeled shift cost."],
                [
                    "Coverage percent",
                    "Workforce Control: (buffered total - uncovered) / buffered total; when demand is zero it displays 100%.",
                ],
                [
                    "MAE / RMSE",
                    "Rolling-origin hourly forecast errors in scenario calls/hour; retrospective diagnostics, not a guarantee.",
                ],
            ],
            [1.45 * inch, CONTENT_WIDTH - 1.45 * inch],
        ),
        paragraph("Recommended scenario workflow", "SubHeading"),
    ]
    story.extend(
        bullet(text)
        for text in [
            "Refresh the request source and verify the latest source date and selected borough.",
            "Replace the request-to-call conversion with a factor calibrated from matched ACD calls and service requests; do not infer the factor from the dashboard itself.",
            "Provide authorized roster availability, shift eligibility, wage, and per-agent workload limits where applicable.",
            "Set handling capacity from measured handle time and an approved occupancy ceiling; separately validate break placement and staffing policies.",
            "Choose budget and demand reserve, calculate the plan, and review hourly shortfalls and solver status before considering the shifts.",
            "Treat the output as a candidate planning artifact. A supervisor must validate the schedule, service obligations, employee availability, and labor rules before release.",
        ]
    )
    story.extend(
        [
            paragraph("7. Assumptions, exclusions, and model risks", "SectionHeading"),
            make_table(
                ["Included simplification", "What it excludes / consequence"],
                [
                    [
                        "24 independent hourly demand balances",
                        "No queue/backlog state, wait time, abandonment, callback, or call transfer dynamics.",
                    ],
                    [
                        "One-day candidate shifts",
                        "No overnight/cross-midnight shift, multi-day rest, overtime, or locked in-progress shifts.",
                    ],
                    [
                        "Single pooled service capacity",
                        "No skills, language groups, call types, team routing, or priority classes.",
                    ],
                    [
                        "One reduced-capacity midpoint hour",
                        "No actual break windows, paid/unpaid break rules, or sub-hour schedule.",
                    ],
                    [
                        "Fixed hourly capacity and shift caps",
                        "No stochastic handle-time distribution, occupancy dynamics, shrinkage profile, or agent-specific speed unless represented by roster caps.",
                    ],
                    [
                        "Deterministic forecast and budget",
                        "No robust/stochastic optimization, forecast confidence intervals, or explicit uncertainty penalties.",
                    ],
                    [
                        "Request proxy for call demand",
                        "Request arrivals can differ materially from phone volume; conversion assumptions can bias staffing.",
                    ],
                    [
                        "Hourly wage times shift hours",
                        "No benefits, differentials, overtime premiums, payroll overhead, or schedule-specific compensation rules.",
                    ],
                ],
                [2.15 * inch, CONTENT_WIDTH - 2.15 * inch],
            ),
            paragraph(
                "The optional Cmin applies only to the total calls assigned to an agent "
                "over a selected shift. It is zero by default because low demand should "
                "not force artificial productivity quotas. A positive minimum may make "
                "the problem infeasible or distort allocations when feasible work is "
                "scarce. Cmax is also per completed shift; the separate hourly capacity "
                "constraint remains necessary to prevent excessive hourly load.",
            ),
            paragraph("8. Run, inspect, and maintain", "SectionHeading"),
            make_table(
                ["Dashboard", "Launch from repository root"],
                [
                    ["Hourly Staffing Optimizer", ".venv/bin/python src/workforce_app.py"],
                    [
                        "Supervisor Workforce Control",
                        ".venv/bin/python src/workforce_control_app.py",
                    ],
                ],
                [2.25 * inch, CONTENT_WIDTH - 2.25 * inch],
            ),
            paragraph(
                "Both apps default to loopback access. Open ports 8051 and 8052 "
                "respectively. Relevant implementation files are "
                "<b>src/nyc311_data.py</b> (source aggregation), "
                "<b>src/workforce_optimizer.py</b> (baseline forecast, roster parsing, "
                "MILP), <b>src/workforce_control.py</b> (percentile forecast and "
                "backtest), <b>src/workforce_app.py</b>, and "
                "<b>src/workforce_control_app.py</b>. Automated MILP and forecast "
                "regression tests are in <b>tests/test_workforce_optimizer.py</b> and "
                "<b>tests/test_workforce_control.py</b>.",
            ),
            paragraph(
                "To regenerate this standalone PDF after changing the model or its "
                "documented controls, run "
                "<b>.venv/bin/python scripts/generate_workforce_technical_pdf.py</b>. "
                "Confirm the generated file opens, its page count is reasonable, and "
                "the formulas and assumptions remain consistent with the code.",
            ),
            paragraph(
                "Prepared 24 October 2026. Values in this document describe application "
                "defaults and source-code behavior at preparation time; live NYC Open "
                "Data values continue to change.",
                "SmallNote",
            ),
        ]
    )
    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.62 * inch,
        title="NYC 311 Workforce Optimization Technical Reference",
        author="NYC 311 Analytics Project",
        subject="Technical documentation for the Hourly Staffing Optimizer and Workforce Control dashboards",
    )
    document.build(build_story(), onFirstPage=page_chrome, onLaterPages=page_chrome)
    print(f"Generated {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
