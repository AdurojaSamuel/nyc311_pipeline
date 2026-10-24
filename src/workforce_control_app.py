#!/usr/bin/env python3
"""Supervisor-oriented daily workforce plan dashboard."""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, State, dcc, html, no_update

from nyc311_data import load_recent_hourly_requests
from workforce_control import forecast_control_demand
from workforce_optimizer import optimize_hourly_staffing

LOGGER = logging.getLogger(__name__)
BOROUGHS = [
    "ALL",
    "BRONX",
    "BROOKLYN",
    "MANHATTAN",
    "QUEENS",
    "STATEN ISLAND",
    "UNKNOWN",
    "UNSPECIFIED",
]
SHIFT_STARTS = [0, 4, 8, 12, 16]
COLORS = {
    "ink": "#eaf2f7",
    "muted": "#91a4b4",
    "canvas": "#07121b",
    "surface": "#0c1c28",
    "surface_alt": "#102635",
    "border": "#244052",
    "cyan": "#38c6d9",
    "amber": "#ffb84d",
    "red": "#ff6b65",
    "green": "#59d69d",
}
PANEL_STYLE = {
    "backgroundColor": COLORS["surface"],
    "border": f"1px solid {COLORS['border']}",
    "borderRadius": "12px",
    "padding": "20px",
}
LABEL_STYLE = {
    "display": "flex",
    "justifyContent": "space-between",
    "gap": "10px",
    "marginTop": "18px",
    "color": COLORS["ink"],
    "fontSize": "13px",
    "fontWeight": 600,
}


def _load_initial_history() -> tuple[pd.DataFrame, str]:
    return load_recent_hourly_requests(days=120)


HISTORY, SOURCE_UPDATED = _load_initial_history()
TODAY_NEW_YORK = pd.Timestamp.now(tz="America/New_York").date()
INITIAL_PLAN_DATE = max(
    TODAY_NEW_YORK + timedelta(days=1),
    pd.Timestamp(SOURCE_UPDATED).date() + timedelta(days=1),
)
INITIAL_FORECAST, _ = forecast_control_demand(
    HISTORY,
    INITIAL_PLAN_DATE,
    calls_per_request=0.05,
)
INITIAL_PEAK_HOUR = int(
    INITIAL_FORECAST.loc[INITIAL_FORECAST["forecast_requests_proxy"].idxmax(), "hour"]
)
INITIAL_FIGURE = go.Figure(
    go.Bar(
        x=INITIAL_FORECAST["hour"],
        y=INITIAL_FORECAST["forecast_calls"],
        name="Forecast call scenario",
        marker_color=COLORS["cyan"],
        customdata=INITIAL_FORECAST["forecast_requests_proxy"],
        hovertemplate="Hour %{x}:00<br>Calls: %{y}<br>Request proxy: %{customdata}<extra></extra>",
    )
)
INITIAL_FIGURE.update_layout(
    template="plotly_dark",
    paper_bgcolor=COLORS["surface"],
    plot_bgcolor=COLORS["surface"],
    height=370,
    margin={"l": 45, "r": 50, "t": 18, "b": 45},
    xaxis={"title": "Hour of day", "tickmode": "linear", "dtick": 2, "gridcolor": COLORS["border"]},
    yaxis={"title": "Calls", "gridcolor": COLORS["border"]},
)
app = Dash(__name__, title="NYC311 Workforce Control")
server = app.server


def _kpi_card(
    title: str,
    value_id: str,
    subtitle: str,
    detail_id: str | None = None,
    initial_value: str = "—",
):
    detail = (
        html.Small("—", id=detail_id, style={"color": COLORS["muted"]})
        if detail_id
        else html.Small(subtitle, style={"color": COLORS["muted"]})
    )
    return html.Div(
        [
            html.Small(title, style={"color": COLORS["muted"]}),
            html.Strong(
                initial_value,
                id=value_id,
                style={"fontSize": "26px", "display": "block", "margin": "10px 0 4px"},
            ),
            detail,
        ],
        style=PANEL_STYLE,
    )


def _panel_heading(kicker: str, title: str):
    return html.Div(
        [
            html.P(
                kicker,
                style={
                    "color": COLORS["cyan"],
                    "fontSize": "10px",
                    "letterSpacing": "1px",
                    "margin": "0",
                },
            ),
            html.H2(title, style={"fontSize": "18px", "margin": "5px 0 10px"}),
        ]
    )


def _check_item(title: str, detail: str):
    return html.Li(
        [
            html.Span("✓", style={"color": COLORS["green"], "marginRight": "9px"}),
            html.Strong(title),
            html.Small(
                detail,
                style={
                    "display": "block",
                    "color": COLORS["muted"],
                    "margin": "3px 0 10px 21px",
                },
            ),
        ]
    )


app.layout = html.Div(
    [
        html.Header(
            [
                html.Div(
                    [
                        html.Span(
                            "311",
                            style={
                                "backgroundColor": COLORS["cyan"],
                                "color": COLORS["canvas"],
                                "fontWeight": 900,
                                "padding": "7px 9px",
                                "borderRadius": "7px",
                                "marginRight": "12px",
                            },
                        ),
                        html.Span(
                            [
                                html.Strong("Workforce Control"),
                                html.Small("Daily staffing plan"),
                            ],
                            style={"display": "inline-grid", "gap": "3px"},
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center"},
                ),
                html.Div(
                    [
                        html.Span(
                            "LIVE REQUEST PROXY",
                            style={
                                "color": COLORS["amber"],
                                "border": f"1px solid {COLORS['amber']}",
                                "borderRadius": "14px",
                                "padding": "5px 10px",
                                "fontSize": "11px",
                                "fontWeight": 700,
                            },
                        ),
                        html.Span(f"Source through {SOURCE_UPDATED}", id="source-date"),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "gap": "16px",
                        "fontSize": "12px",
                        "color": COLORS["muted"],
                    },
                ),
            ],
            style={
                "height": "72px",
                "borderBottom": f"1px solid {COLORS['border']}",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
                "padding": "0 24px",
                "position": "sticky",
                "top": 0,
                "zIndex": 10,
                "backgroundColor": COLORS["canvas"],
                "width": "100%",
            },
            className="control-header",
        ),
        html.Main(
            [
                dcc.Store(id="hourly-data", data=HISTORY.to_dict("records")),
                html.Section(
                    [
                        html.Div(
                            [
                                html.P(
                                    [
                                        "OPERATIONS · ",
                                        html.Span(
                                            INITIAL_PLAN_DATE.isoformat(),
                                            id="plan-date-label",
                                        ),
                                    ],
                                    style={
                                        "color": COLORS["cyan"],
                                        "fontSize": "11px",
                                        "letterSpacing": "1px",
                                        "fontWeight": 700,
                                    },
                                ),
                                html.H1(
                                    "Tomorrow's call floor",
                                    style={"fontSize": "32px", "margin": "8px 0"},
                                ),
                                html.P(
                                    "A current-data, budget-aware shift scenario for supervisor review.",
                                    style={"color": COLORS["muted"], "margin": 0},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Span(id="status-indicator", style={"color": COLORS["amber"]}),
                                html.Div(
                                    [
                                        html.Small("PLAN STATUS", style={"color": COLORS["muted"]}),
                                        html.Strong("Scenario pending", id="plan-status"),
                                    ],
                                    style={"display": "grid", "gap": "4px"},
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center", "gap": "10px"},
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "gap": "20px",
                        "margin": "28px 0 20px",
                    },
                ),
                html.Div(
                    [
                        html.Div(
                            "!",
                            style={
                                "color": COLORS["red"],
                                "fontSize": "24px",
                                "fontWeight": 800,
                            },
                        ),
                        html.Div(
                            [
                                html.Strong(
                                    "Budget or coverage constraint detected", id="alert-title"
                                ),
                                html.P(
                                    "Calculate a scenario to review plan feasibility.",
                                    id="alert-copy",
                                    style={"color": COLORS["muted"], "margin": "5px 0 0"},
                                ),
                            ],
                            style={"flex": 1},
                        ),
                        html.A(
                            "Review controls",
                            href="#scenario-controls",
                            style={
                                "color": COLORS["ink"],
                                "border": f"1px solid {COLORS['border']}",
                                "borderRadius": "6px",
                                "padding": "9px 12px",
                                "textDecoration": "none",
                                "fontSize": "12px",
                            },
                        ),
                    ],
                    id="risk-alert",
                    style={
                        **PANEL_STYLE,
                        "display": "none",
                        "alignItems": "center",
                        "gap": "14px",
                        "borderColor": COLORS["red"],
                        "marginBottom": "16px",
                    },
                ),
                html.Section(
                    [
                        _kpi_card(
                            "Forecast SRs",
                            "forecast-srs",
                            "24-hour current-data proxy",
                            initial_value=f"{int(INITIAL_FORECAST['forecast_requests_proxy'].sum()):,}",
                        ),
                        _kpi_card("Agent shifts", "agent-shifts", "Eight-hour planning shifts"),
                        _kpi_card(
                            "Labor spend", "labor-spend", "budget remaining", "budget-remaining"
                        ),
                        _kpi_card(
                            "Uncovered SR proxy",
                            "uncovered",
                            "buffered demand coverage",
                            "coverage",
                        ),
                    ],
                    style={
                        "display": "grid",
                        "gridTemplateColumns": "repeat(4, minmax(0, 1fr))",
                        "gap": "12px",
                        "marginBottom": "16px",
                    },
                    className="kpi-grid",
                ),
                html.Section(
                    [
                        html.Article(
                            [
                                _panel_heading("HOURLY COVERAGE", "Demand vs safe capacity"),
                                dcc.Graph(
                                    id="coverage-chart",
                                    figure=INITIAL_FIGURE,
                                    config={"displaylogo": False, "responsive": True},
                                ),
                                html.P(
                                    f"Peak forecast request proxy: "
                                    f"{int(INITIAL_FORECAST['forecast_requests_proxy'].max()):,} "
                                    f"at {INITIAL_PEAK_HOUR:02d}:00. Calculate a scenario to review "
                                    "safe capacity, costs, and rolling-origin validation.",
                                    id="peak-note",
                                    style={"color": COLORS["muted"], "fontSize": "12px"},
                                ),
                            ],
                            style=PANEL_STYLE,
                            className="coverage-panel",
                        ),
                        html.Aside(
                            [
                                _panel_heading("SCENARIO CONTROLS", "Operating limits"),
                                html.Label(
                                    [
                                        "Daily labor budget",
                                        html.Output("$15,500", id="budget-output"),
                                    ],
                                    htmlFor="budget",
                                    style=LABEL_STYLE,
                                ),
                                dcc.Slider(
                                    id="budget",
                                    min=5000,
                                    max=25000,
                                    step=250,
                                    value=15500,
                                    marks={5000: "$5k", 15000: "$15k", 25000: "$25k"},
                                    tooltip={"placement": "bottom", "always_visible": False},
                                ),
                                html.Label(
                                    [
                                        "Max calls / agent / hour",
                                        html.Output("8", id="hourly-cap-output"),
                                    ],
                                    htmlFor="max-hourly",
                                    style=LABEL_STYLE,
                                ),
                                dcc.Slider(
                                    id="max-hourly",
                                    min=4,
                                    max=12,
                                    step=1,
                                    value=8,
                                    marks={4: "4", 8: "8", 12: "12"},
                                ),
                                html.Label(
                                    ["Demand buffer", html.Output("112%", id="buffer-output")],
                                    htmlFor="demand-buffer",
                                    style=LABEL_STYLE,
                                ),
                                dcc.Slider(
                                    id="demand-buffer",
                                    min=1.0,
                                    max=1.3,
                                    step=0.01,
                                    value=1.12,
                                    marks={1: "100%", 1.15: "115%", 1.3: "130%"},
                                ),
                                html.Label(
                                    [
                                        "Max calls / agent / shift",
                                        html.Output("52", id="shift-cap-output"),
                                    ],
                                    htmlFor="max-shift",
                                    style=LABEL_STYLE,
                                ),
                                dcc.Slider(
                                    id="max-shift",
                                    min=32,
                                    max=72,
                                    step=2,
                                    value=52,
                                    marks={32: "32", 52: "52", 72: "72"},
                                ),
                                html.Label(
                                    [
                                        "Optional minimum / shift",
                                        html.Output("0", id="min-shift-output"),
                                    ],
                                    htmlFor="min-shift",
                                    style=LABEL_STYLE,
                                ),
                                dcc.Slider(
                                    id="min-shift",
                                    min=0,
                                    max=32,
                                    step=2,
                                    value=0,
                                    marks={0: "Off", 16: "16", 32: "32"},
                                ),
                                html.Label(
                                    "Calls per service request (scenario factor)", style=LABEL_STYLE
                                ),
                                dcc.Input(
                                    id="calls-per-request",
                                    type="number",
                                    min=0,
                                    max=5,
                                    step=0.01,
                                    value=0.05,
                                    style={
                                        "width": "100%",
                                        "backgroundColor": COLORS["surface_alt"],
                                        "color": COLORS["ink"],
                                        "border": f"1px solid {COLORS['border']}",
                                        "borderRadius": "5px",
                                        "padding": "8px",
                                        "marginTop": "8px",
                                    },
                                ),
                                html.Label("Plan date and borough", style=LABEL_STYLE),
                                dcc.DatePickerSingle(
                                    id="plan-date",
                                    date=INITIAL_PLAN_DATE,
                                    min_date_allowed=pd.Timestamp(SOURCE_UPDATED).date()
                                    + timedelta(days=1),
                                    display_format="YYYY-MM-DD",
                                ),
                                dcc.Dropdown(
                                    id="borough",
                                    options=[
                                        {"label": name.title(), "value": name} for name in BOROUGHS
                                    ],
                                    value="ALL",
                                    clearable=False,
                                    style={"marginTop": "10px", "color": "#18232c"},
                                ),
                                html.Label("Available agents", style=LABEL_STYLE),
                                dcc.Input(
                                    id="available-agents",
                                    type="number",
                                    min=1,
                                    max=250,
                                    step=1,
                                    value=35,
                                    style={
                                        "width": "100%",
                                        "backgroundColor": COLORS["surface_alt"],
                                        "color": COLORS["ink"],
                                        "border": f"1px solid {COLORS['border']}",
                                        "borderRadius": "5px",
                                        "padding": "8px",
                                        "marginTop": "8px",
                                    },
                                ),
                                html.Label("Hourly wage ($)", style=LABEL_STYLE),
                                dcc.Input(
                                    id="hourly-wage",
                                    type="number",
                                    min=0,
                                    step=0.5,
                                    value=31.5,
                                    style={
                                        "width": "100%",
                                        "backgroundColor": COLORS["surface_alt"],
                                        "color": COLORS["ink"],
                                        "border": f"1px solid {COLORS['border']}",
                                        "borderRadius": "5px",
                                        "padding": "8px",
                                        "marginTop": "8px",
                                    },
                                ),
                                html.Button(
                                    "Calculate scenario",
                                    id="calculate",
                                    n_clicks=0,
                                    style={
                                        "width": "100%",
                                        "marginTop": "20px",
                                        "padding": "12px",
                                        "border": 0,
                                        "borderRadius": "6px",
                                        "backgroundColor": COLORS["cyan"],
                                        "color": COLORS["canvas"],
                                        "fontWeight": 800,
                                        "cursor": "pointer",
                                    },
                                ),
                                html.Button(
                                    "Refresh live request data",
                                    id="refresh",
                                    n_clicks=0,
                                    style={
                                        "width": "100%",
                                        "marginTop": "8px",
                                        "padding": "10px",
                                        "border": f"1px solid {COLORS['border']}",
                                        "borderRadius": "6px",
                                        "backgroundColor": COLORS["surface_alt"],
                                        "color": COLORS["ink"],
                                    },
                                ),
                                html.P(
                                    "Budget and workload limits are enforced as hard constraints. "
                                    "When those limits prevent full coverage, the plan reports the "
                                    "shortfall instead of assigning overload.",
                                    style={
                                        "color": COLORS["muted"],
                                        "fontSize": "12px",
                                        "lineHeight": 1.5,
                                    },
                                ),
                            ],
                            id="scenario-controls",
                            style=PANEL_STYLE,
                            className="scenario-panel",
                        ),
                    ],
                    style={
                        "display": "grid",
                        "gridTemplateColumns": "minmax(0, 2.1fr) minmax(290px, 0.9fr)",
                        "gap": "12px",
                        "marginBottom": "16px",
                    },
                    className="control-workspace",
                ),
                html.Section(
                    [
                        html.Article(
                            [
                                html.Div(
                                    [
                                        _panel_heading("SHIFT RELEASE", "Recommended starts"),
                                        html.Button(
                                            "Export plan",
                                            id="export-plan",
                                            n_clicks=0,
                                            style={
                                                "backgroundColor": COLORS["surface_alt"],
                                                "color": COLORS["ink"],
                                                "border": f"1px solid {COLORS['border']}",
                                                "borderRadius": "6px",
                                                "padding": "9px 12px",
                                            },
                                        ),
                                    ],
                                    style={
                                        "display": "flex",
                                        "justifyContent": "space-between",
                                        "alignItems": "center",
                                        "gap": "12px",
                                    },
                                ),
                                html.Div(
                                    id="shift-table",
                                    children="Calculate a scenario to see recommended shifts.",
                                ),
                                dcc.Download(id="plan-download"),
                                dcc.Store(id="plan-store"),
                            ],
                            style=PANEL_STYLE,
                        ),
                        html.Aside(
                            [
                                _panel_heading("DATA & SAFETY", "Release checks"),
                                html.Ul(
                                    [
                                        _check_item(
                                            "Current source",
                                            "Public NYC 311 aggregates; date shown above.",
                                        ),
                                        _check_item(
                                            "Workload limits",
                                            "Hourly and per-shift maxima enforced by MILP.",
                                        ),
                                        _check_item(
                                            "Budget ceiling",
                                            "Complete-shift cost cannot exceed scenario budget.",
                                        ),
                                        _check_item(
                                            "Human review",
                                            "Export is a planning artifact, not a published roster.",
                                        ),
                                    ],
                                    style={"paddingLeft": "18px", "lineHeight": 1.6},
                                ),
                                html.P(
                                    "NYC 311 contains service-request records, not ACD phone arrivals or "
                                    "staffing records. The request-to-call factor, wage, and staffing "
                                    "assumptions are scenario values that require validation.",
                                    style={
                                        "color": COLORS["amber"],
                                        "fontSize": "12px",
                                        "lineHeight": 1.5,
                                        "borderTop": f"1px solid {COLORS['border']}",
                                        "paddingTop": "12px",
                                    },
                                ),
                                html.Div(
                                    id="validation-note",
                                    style={"color": COLORS["muted"], "fontSize": "12px"},
                                ),
                            ],
                            style=PANEL_STYLE,
                        ),
                    ],
                    style={
                        "display": "grid",
                        "gridTemplateColumns": "minmax(0, 2.1fr) minmax(290px, 0.9fr)",
                        "gap": "12px",
                        "marginBottom": "30px",
                    },
                    className="release-workspace",
                ),
                html.Div(
                    [
                        html.A(
                            "Monthly Python dashboard",
                            href="http://localhost:8050",
                            style={"color": COLORS["cyan"]},
                        ),
                        html.Span(" · ", style={"color": COLORS["muted"]}),
                        html.A(
                            "R Shiny dashboard",
                            href="http://localhost:3838",
                            style={"color": COLORS["cyan"]},
                        ),
                        html.Span(" · ", style={"color": COLORS["muted"]}),
                        html.A(
                            "Hourly optimizer",
                            href="http://localhost:8051",
                            style={"color": COLORS["cyan"]},
                        ),
                    ],
                    style={
                        "borderTop": f"1px solid {COLORS['border']}",
                        "padding": "18px 0 30px",
                        "fontSize": "12px",
                    },
                ),
            ],
            style={"maxWidth": "1440px", "margin": "0 auto", "padding": "0 24px"},
            className="control-main",
        ),
    ],
    style={
        "backgroundColor": COLORS["canvas"],
        "color": COLORS["ink"],
        "minHeight": "100vh",
        "fontFamily": "Inter, system-ui, sans-serif",
        "fontSize": "14px",
        "lineHeight": 1.45,
    },
)


@app.callback(
    Output("source-date", "children"),
    Output("hourly-data", "data"),
    Output("plan-date", "min_date_allowed"),
    Output("plan-date", "date"),
    Input("refresh", "n_clicks"),
    State("plan-date", "date"),
    prevent_initial_call=True,
)
def refresh_source(_clicks: int, current_plan_date: str | None):
    try:
        data, updated = load_recent_hourly_requests(days=120)
    except (requests.RequestException, RuntimeError) as error:
        LOGGER.exception("Could not refresh NYC 311 hourly source data.")
        return f"Refresh failed: {error}", no_update, no_update, no_update
    minimum_date = pd.Timestamp(updated).date() + timedelta(days=1)
    new_plan_date = max(
        pd.Timestamp(current_plan_date).date() if current_plan_date else minimum_date,
        minimum_date,
        TODAY_NEW_YORK + timedelta(days=1),
    )
    return f"Source through {updated}", data.to_dict("records"), minimum_date, new_plan_date


@app.callback(
    Output("budget-output", "children"),
    Output("hourly-cap-output", "children"),
    Output("buffer-output", "children"),
    Output("shift-cap-output", "children"),
    Output("min-shift-output", "children"),
    Input("budget", "value"),
    Input("max-hourly", "value"),
    Input("demand-buffer", "value"),
    Input("max-shift", "value"),
    Input("min-shift", "value"),
)
def update_control_labels(budget, hourly_cap, buffer, shift_cap, min_shift):
    if any(value is None for value in (budget, hourly_cap, buffer, shift_cap, min_shift)):
        return "$—", "—", "—", "—", "—"
    return (
        f"${int(budget):,}",
        str(int(hourly_cap)),
        f"{float(buffer):.0%}",
        str(int(shift_cap)),
        str(int(min_shift)),
    )


@app.callback(
    Output("coverage-chart", "figure"),
    Output("plan-date-label", "children"),
    Output("plan-status", "children"),
    Output("status-indicator", "children"),
    Output("status-indicator", "style"),
    Output("alert-title", "children"),
    Output("alert-copy", "children"),
    Output("risk-alert", "style"),
    Output("forecast-srs", "children"),
    Output("agent-shifts", "children"),
    Output("labor-spend", "children"),
    Output("budget-remaining", "children"),
    Output("uncovered", "children"),
    Output("coverage", "children"),
    Output("peak-note", "children"),
    Output("shift-table", "children"),
    Output("validation-note", "children"),
    Output("plan-store", "data"),
    Input("calculate", "n_clicks"),
    State("hourly-data", "data"),
    State("plan-date", "date"),
    State("borough", "value"),
    State("budget", "value"),
    State("max-hourly", "value"),
    State("demand-buffer", "value"),
    State("max-shift", "value"),
    State("min-shift", "value"),
    State("calls-per-request", "value"),
    State("available-agents", "value"),
    State("hourly-wage", "value"),
    prevent_initial_call=True,
)
def calculate_scenario(
    _clicks,
    history_records,
    plan_date,
    borough,
    budget,
    max_hourly,
    demand_buffer,
    max_shift,
    min_shift,
    calls_per_request,
    available_agents,
    hourly_wage,
):
    try:
        values = (
            plan_date,
            borough,
            budget,
            max_hourly,
            demand_buffer,
            max_shift,
            min_shift,
            calls_per_request,
            available_agents,
            hourly_wage,
        )
        if any(value is None for value in values):
            raise ValueError("Complete all scenario controls before calculating the plan.")
        if not history_records:
            raise ValueError("No current hourly data is available; refresh the source and retry.")
        if not 1.0 <= float(demand_buffer) <= 1.3:
            raise ValueError("Demand buffer must be between 100% and 130%.")
        if not 0 <= float(calls_per_request) <= 5:
            raise ValueError("Calls per service request must be between 0 and 5.")

        history = pd.DataFrame.from_records(history_records)
        latest_source_date = (
            pd.to_datetime(history["day"], errors="raise").max().strftime("%Y-%m-%d")
        )
        forecast, metrics = forecast_control_demand(
            history,
            plan_date,
            borough,
            history_days=56,
            percentile=0.75,
            calls_per_request=float(calls_per_request),
        )
        forecast["buffered_calls"] = (forecast["forecast_calls"] * float(demand_buffer)).apply(
            lambda count: int(round(count))
        )
        solver_demand = forecast.assign(forecast_calls=forecast["buffered_calls"])
        solution = optimize_hourly_staffing(
            solver_demand,
            available_agents=int(available_agents),
            shift_starts=SHIFT_STARTS,
            shift_length=8,
            hourly_capacity=float(max_hourly),
            break_hour_offset=4,
            break_capacity_factor=0.5,
            max_calls_per_shift=int(max_shift),
            min_calls_per_shift=int(min_shift),
            hourly_wage=float(hourly_wage),
            daily_budget=float(budget),
        )
    except (ValueError, RuntimeError) as error:
        LOGGER.exception("Could not calculate the workforce scenario.")
        return (
            no_update,
            str(plan_date or "—"),
            "Action required",
            "●",
            {"color": COLORS["red"], "fontSize": "18px"},
            "Scenario calculation failed",
            str(error),
            {
                **PANEL_STYLE,
                "display": "flex",
                "alignItems": "center",
                "gap": "14px",
                "borderColor": COLORS["red"],
                "marginBottom": "16px",
            },
            no_update,
            "—",
            "—",
            "—",
            "—",
            "—",
            "No plan generated; correct the scenario inputs and retry.",
            html.P(
                "No updated shift plan is available. Correct the scenario or data issue and try again."
            ),
            f"Scenario error: {error}",
            None,
        )

    chart_data = forecast.merge(
        solution.hourly.rename(columns={"forecast_calls": "buffered_calls"}),
        on=["hour", "buffered_calls"],
        validate="one_to_one",
    )
    chart = go.Figure()
    chart.add_trace(
        go.Bar(
            x=chart_data["hour"],
            y=chart_data["forecast_calls"],
            name="Forecast call scenario",
            marker_color=COLORS["cyan"],
            customdata=chart_data["forecast_requests_proxy"],
            hovertemplate="Hour %{x}:00<br>Calls: %{y}<br>Request proxy: %{customdata}<extra></extra>",
        )
    )
    chart.add_trace(
        go.Bar(
            x=chart_data["hour"],
            y=chart_data["buffered_calls"],
            name="Buffered demand",
            marker_color="rgba(56,198,217,.35)",
        )
    )
    chart.add_trace(
        go.Scatter(
            x=chart_data["hour"],
            y=chart_data["handling_capacity"],
            name="Safe staffed capacity",
            mode="lines+markers",
            line={"color": COLORS["amber"], "width": 2},
            yaxis="y2",
        )
    )
    chart.add_trace(
        go.Scatter(
            x=chart_data["hour"],
            y=chart_data["unmet_calls"],
            name="Uncovered buffered demand",
            mode="markers",
            marker={"color": COLORS["red"], "size": 8},
            yaxis="y2",
        )
    )
    chart.update_layout(
        template="plotly_dark",
        paper_bgcolor=COLORS["surface"],
        plot_bgcolor=COLORS["surface"],
        barmode="overlay",
        height=370,
        margin={"l": 45, "r": 50, "t": 18, "b": 45},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        xaxis={
            "title": "Hour of day",
            "tickmode": "linear",
            "dtick": 2,
            "gridcolor": COLORS["border"],
        },
        yaxis={"title": "Calls", "gridcolor": COLORS["border"]},
        yaxis2={
            "title": "Capacity / shortfall",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
        },
    )
    hourly_max = int(forecast.loc[forecast["forecast_requests_proxy"].idxmax(), "hour"])
    peak_requests = int(forecast["forecast_requests_proxy"].max())
    shifts = solution.assignments.groupby("shift_start", as_index=False).agg(
        agents=("agent", "count"),
        expected_calls=("calls_assigned", "sum"),
        shift_cost=("shift_cost", "sum"),
    )
    shifts["calls_per_agent"] = shifts["expected_calls"] / shifts["agents"]
    shifts["load"] = shifts["calls_per_agent"] / int(max_shift) if int(max_shift) else 0
    shift_rows = _make_shift_table(shifts, int(min_shift))
    buffered_total = int(forecast["buffered_calls"].sum())
    covered_total = buffered_total - solution.unmet_calls
    coverage_percent = 100.0 if buffered_total == 0 else 100 * covered_total / buffered_total
    optimal = "optimal" in solution.solver_status.lower()
    feasible = solution.unmet_calls == 0 and optimal
    state_color = COLORS["green"] if feasible else COLORS["amber"]
    status = "Ready for review" if feasible else "Action required"
    if solution.unmet_calls:
        alert_title = "Budget or capacity constraint detected"
        alert_copy = (
            f"{solution.unmet_calls:,} buffered calls remain uncovered. Review the budget and demand "
            "buffer, or arrange an approved overflow plan; workload caps remain enforced."
        )
    elif not optimal:
        alert_title = "Solver did not prove an optimal plan"
        alert_copy = f"The solver returned: {solution.solver_status}. Review the result before use."
    else:
        alert_title = "Coverage fits within the modeled limits"
        alert_copy = (
            "No buffered calls remain uncovered. Review the assumptions and approve before release."
        )
    alert_style = {
        **PANEL_STYLE,
        "display": "flex",
        "alignItems": "center",
        "gap": "14px",
        "borderColor": state_color,
        "marginBottom": "16px",
    }
    peak_note = (
        f"Peak forecast request proxy: {peak_requests:,} at {hourly_max:02d}:00. "
        f"Rolling-origin validation: MAE {metrics['validation_mae']:.2f} and "
        f"RMSE {metrics['validation_rmse']:.2f} scenario calls/hour "
        f"over {int(metrics['validation_observations'])} observations."
    )
    plan = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "source": "NYC Open Data 311 service-request creation timestamps",
        "source_updated_through": latest_source_date,
        "plan_date": str(plan_date),
        "borough": borough,
        "status": "feasible" if feasible else "at_risk",
        "config": {
            "daily_budget": float(budget),
            "max_calls_per_agent_hour": int(max_hourly),
            "demand_buffer": float(demand_buffer),
            "max_calls_per_agent_shift": int(max_shift),
            "min_calls_per_agent_shift": int(min_shift),
            "calls_per_request_scenario_factor": float(calls_per_request),
            "hourly_wage": float(hourly_wage),
            "shift_length_hours": 8,
            "shift_starts": SHIFT_STARTS,
            "forecast_history_days": 56,
            "forecast_percentile": 0.75,
        },
        "summary": {
            "forecast_request_proxy": int(forecast["forecast_requests_proxy"].sum()),
            "forecast_calls": int(forecast["forecast_calls"].sum()),
            "buffered_calls": buffered_total,
            "scheduled_agent_shifts": len(solution.assignments),
            "daily_spend": solution.total_cost,
            "budget_remaining": solution.budget_remaining,
            "uncovered_calls": solution.unmet_calls,
            "coverage_percent": coverage_percent,
            "solver_status": solution.solver_status,
        },
        "hourly": chart_data.to_dict("records"),
        "shifts": shifts.to_dict("records"),
        "validation": metrics,
    }
    return (
        chart,
        str(plan_date),
        status,
        "●",
        {"color": state_color, "fontSize": "18px"},
        alert_title,
        alert_copy,
        alert_style,
        f"{int(forecast['forecast_requests_proxy'].sum()):,}",
        f"{len(solution.assignments):,}",
        f"${solution.total_cost:,.0f}",
        f"${solution.budget_remaining:,.0f} remaining",
        f"{solution.unmet_calls:,}",
        f"{coverage_percent:.1f}% covered",
        peak_note,
        shift_rows,
        f"Solver: {solution.solver_status}. Service-shortfall optimization is followed by shift-cost minimization; export remains a supervisor-review artifact.",
        plan,
    )


def _make_shift_table(shifts: pd.DataFrame, minimum_calls: int) -> html.Div:
    if shifts.empty:
        return html.P("No shifts fit the current constraints.", style={"color": COLORS["muted"]})
    columns = ["Start", "End", "Agents", "Expected calls", "Calls / agent", "Load"]
    head = html.Thead(html.Tr([html.Th(name) for name in columns]))
    rows = []
    for row in shifts.itertuples(index=False):
        start = int(str(row.shift_start).split(":")[0])
        end = (start + 8) % 24
        if row.load > 0.85:
            load, load_color = "Near cap", COLORS["amber"]
        elif minimum_calls and row.calls_per_agent < minimum_calls:
            load, load_color = "Light", COLORS["amber"]
        else:
            load, load_color = "Balanced", COLORS["green"]
        cells = [
            f"{start:02d}:00",
            f"{end:02d}:00",
            f"{row.agents:,}",
            f"{row.expected_calls:,.0f}",
            f"{row.calls_per_agent:.1f}",
            html.Span(load, style={"color": load_color}),
        ]
        rows.append(html.Tr([html.Td(value) for value in cells]))
    return html.Div(
        html.Table(
            [head, html.Tbody(rows)],
            style={
                "width": "100%",
                "borderCollapse": "collapse",
                "fontSize": "12px",
                "textAlign": "left",
            },
        ),
        style={"overflowX": "auto"},
    )


@app.callback(
    Output("plan-download", "data"),
    Input("export-plan", "n_clicks"),
    State("plan-store", "data"),
    prevent_initial_call=True,
)
def export_plan(_clicks: int, plan: dict | None):
    if not plan:
        return no_update
    encoded = json.dumps(plan, indent=2, default=str)
    return dcc.send_string(encoded, f"nyc311-staffing-{plan['plan_date']}.json")


if __name__ == "__main__":
    app.run(
        debug=os.getenv("DASH_DEBUG", "0") == "1",
        host=os.getenv("DASH_HOST", "127.0.0.1"),
        port=int(os.getenv("WORKFORCE_CONTROL_PORT", "8052")),
    )
