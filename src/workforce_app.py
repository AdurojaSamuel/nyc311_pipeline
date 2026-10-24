#!/usr/bin/env python3
"""Interactive hourly NYC 311 workforce optimization dashboard."""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html

from nyc311_data import load_recent_hourly_requests
from workforce_optimizer import (
    forecast_hourly_demand,
    optimize_hourly_staffing,
    parse_agent_roster,
)

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
SHIFT_STARTS = [
    {"label": f"{hour:02d}:00", "value": hour}
    for hour in (0, 4, 8, 12, 16)
]
STYLE = {
    "fontFamily": "Arial, sans-serif",
    "color": "#233044",
    "backgroundColor": "#f5f7fa",
    "minHeight": "100vh",
    "padding": "22px",
}
CARD_STYLE = {
    "backgroundColor": "white",
    "border": "1px solid #dce3ec",
    "borderRadius": "8px",
    "padding": "16px",
    "marginBottom": "14px",
}
LABEL_STYLE = {"display": "block", "fontWeight": 700, "marginTop": "12px"}
CONTROL_STYLE = {"width": "100%", "padding": "8px", "boxSizing": "border-box"}


def _load_initial_history() -> tuple[pd.DataFrame, str]:
    return load_recent_hourly_requests(days=120)


HISTORY, SOURCE_UPDATED = _load_initial_history()
INITIAL_TARGET = max(date.today() + timedelta(days=1), pd.Timestamp(SOURCE_UPDATED).date() + timedelta(days=1))

app = Dash(__name__, title="NYC311 Hourly Workforce Optimization")
server = app.server

app.layout = html.Main(
    [
        html.H1("NYC311 Call Center Workforce Optimization"),
        html.P(
            "Forecast hourly service-request arrivals, translate them into a configurable call-demand "
            "scenario, and solve a budget-constrained integer shift-allocation model."
        ),
        html.Div(
            [
                html.Strong("Data and scope note"),
                html.P(
                    "NYC Open Data publishes service-request creation timestamps, not call-center ACD "
                    "arrivals, agent rosters, handling times, or labor contracts. Hourly requests are "
                    "therefore a current demand proxy, not observed phone calls. Set the calls-per-request "
                    "factor and staffing inputs from verified call-center records before operational use."
                ),
                html.Div(id="data-status", children=f"Live NYC Open Data requests through {SOURCE_UPDATED}."),
                dcc.Store(id="hourly-data", data=HISTORY.to_dict("records")),
                dcc.Store(id="agent-roster"),
            ],
            style={**CARD_STYLE, "borderLeft": "5px solid #d28b26"},
        ),
        html.Div(
            [
                html.A("Monthly request dashboard", href="http://localhost:8050", target="_blank"),
                html.Span("  |  "),
                html.A("R Shiny dashboard", href="http://localhost:3838", target="_blank"),
            ],
            style={"marginBottom": "14px"},
        ),
        html.Div(
            [
                html.Section(
                    [
                        html.H2("Scenario inputs"),
                        html.Label("Borough", style=LABEL_STYLE),
                        dcc.Dropdown(BOROUGHS, "ALL", id="borough", clearable=False),
                        html.Label("Forecast date", style=LABEL_STYLE),
                        dcc.DatePickerSingle(
                            id="target-date",
                            date=INITIAL_TARGET,
                            min_date_allowed=HISTORY.day.max().date() + timedelta(days=1),
                            display_format="YYYY-MM-DD",
                        ),
                        html.Label("Calls per service request (scenario factor)", style=LABEL_STYLE),
                        dcc.Input(id="calls-per-request", type="number", min=0, step=0.01, value=0.05, style=CONTROL_STYLE),
                        html.Label("Available agents (if no roster is uploaded)", style=LABEL_STYLE),
                        dcc.Input(id="available-agents", type="number", min=1, max=250, step=1, value=35, style=CONTROL_STYLE),
                        html.Label("Eligible shift starts", style=LABEL_STYLE),
                        dcc.Checklist(SHIFT_STARTS, [0, 4, 8, 12, 16], id="shift-starts", inline=True),
                        html.Label("Shift length (hours)", style=LABEL_STYLE),
                        dcc.Input(id="shift-length", type="number", min=1, max=24, step=1, value=8, style=CONTROL_STYLE),
                        html.Label("Daily staffing budget ($)", style=LABEL_STYLE),
                        dcc.Input(id="daily-budget", type="number", min=0, step=100, value=5500, style=CONTROL_STYLE),
                        html.Label("Hourly wage ($)", style=LABEL_STYLE),
                        dcc.Input(id="hourly-wage", type="number", min=0, step=1, value=25, style=CONTROL_STYLE),
                        html.Label("Average handle time (minutes)", style=LABEL_STYLE),
                        dcc.Input(id="handle-time", type="number", min=0.1, step=0.5, value=8, style=CONTROL_STYLE),
                        html.Label("Safe occupancy cap (%)", style=LABEL_STYLE),
                        dcc.Input(id="occupancy", type="number", min=1, max=100, step=1, value=85, style=CONTROL_STYLE),
                        html.Label("Maximum calls per shift (per agent)", style=LABEL_STYLE),
                        dcc.Input(id="max-calls-shift", type="number", min=0, step=1, value=48, style=CONTROL_STYLE),
                        html.Label("Optional minimum calls per completed shift", style=LABEL_STYLE),
                        dcc.Input(id="min-calls-shift", type="number", min=0, step=1, value=0, style=CONTROL_STYLE),
                        html.P(
                            "Minimum is zero by default: it is a per-shift target, not an hourly quota. "
                            "The model can leave calls unserved when budget/capacity is insufficient."
                        ),
                        html.Label("Agent roster CSV (optional)", style=LABEL_STYLE),
                        dcc.Upload(
                            id="roster-upload",
                            children=html.Button("Upload roster CSV"),
                            accept=".csv,text/csv",
                            multiple=False,
                        ),
                        html.Div(id="roster-status", style={"fontSize": "12px", "marginTop": "6px"}),
                        html.P(
                            "Columns: agent_id, eligible_shifts (comma-separated hours), hourly_wage, "
                            "max_calls_per_shift; optional min_calls_per_shift. Without a roster, the "
                            "configured pool is modeled as interchangeable agents.",
                            style={"fontSize": "12px", "color": "#526174"},
                        ),
                        html.Button(
                            "Refresh live request data",
                            id="refresh-data",
                            n_clicks=0,
                            style={"marginTop": "10px"},
                        ),
                        html.Button(
                            "Forecast and optimize",
                            id="solve",
                            n_clicks=0,
                            style={
                                "display": "block",
                                "width": "100%",
                                "padding": "12px",
                                "marginTop": "14px",
                                "backgroundColor": "#0c7c86",
                                "color": "white",
                                "fontWeight": 700,
                                "border": 0,
                                "borderRadius": "5px",
                                "cursor": "pointer",
                            },
                        ),
                    ],
                    style={**CARD_STYLE, "width": "340px", "flex": "0 0 340px"},
                ),
                html.Section(
                    [
                        html.H2("Hourly forecast, service coverage, and cost"),
                        html.Div(id="validation-status", style=CARD_STYLE),
                        html.Div(id="kpis", style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}),
                        dcc.Graph(id="hourly-chart", figure=go.Figure().update_layout(template="plotly_white")),
                        html.H2("Selected shifts and workload"),
                        html.Div(id="schedule-table", style={"overflowX": "auto"}),
                        html.H2("Hourly detail"),
                        html.Div(id="hourly-table", style={"overflowX": "auto"}),
                        html.P(
                            "Model assumptions and limits: 24 one-hour periods; calls are allocated to eligible "
                            "agents and selected shifts; each agent may take one shift; shift caps are daily "
                            "per-shift totals; capacity derives from handle time and occupancy. A scheduled "
                            "30-minute break reduces capacity by half in the shift midpoint hour. This is a "
                            "same-day service-shortfall model, not queue carryover, abandonment, skill routing, "
                            "rest-law verification, or a production schedule. Validate break placement, actual "
                            "shift rules, arrival uncertainty, and safety with agency records."
                        ),
                    ],
                    style={"minWidth": 0, "flex": "1"},
                ),
            ],
            style={"display": "flex", "alignItems": "flex-start", "gap": "14px", "flexWrap": "wrap"},
        ),
    ],
    style=STYLE,
)


def _make_table(frame: pd.DataFrame) -> html.Table:
    header = html.Thead(html.Tr([html.Th(str(column)) for column in frame.columns]))
    body = html.Tbody(
        [
            html.Tr([html.Td(str(value)) for value in row])
            for row in frame.itertuples(index=False, name=None)
        ]
    )
    return html.Table(
        [header, body],
        style={
            "width": "100%",
            "borderCollapse": "collapse",
            "backgroundColor": "white",
            "textAlign": "left",
        },
    )


@app.callback(
    Output("hourly-data", "data"),
    Output("data-status", "children"),
    Input("refresh-data", "n_clicks"),
    prevent_initial_call=True,
)
def refresh_data(_clicks: int):
    data, source_updated = load_recent_hourly_requests(days=120)
    return data.to_dict("records"), f"Live NYC Open Data requests through {source_updated} (all boroughs loaded)."


@app.callback(
    Output("agent-roster", "data"),
    Output("roster-status", "children"),
    Input("roster-upload", "contents"),
    prevent_initial_call=True,
)
def update_roster(contents: str | None):
    if not contents:
        return None, "No roster uploaded; the interchangeable-agent scenario will be used."
    roster = parse_agent_roster(contents)
    return roster, f"Loaded {len(roster)} agent roster rows."


@app.callback(
    Output("hourly-chart", "figure"),
    Output("validation-status", "children"),
    Output("kpis", "children"),
    Output("schedule-table", "children"),
    Output("hourly-table", "children"),
    Input("solve", "n_clicks"),
    State("hourly-data", "data"),
    State("agent-roster", "data"),
    State("target-date", "date"),
    State("borough", "value"),
    State("calls-per-request", "value"),
    State("available-agents", "value"),
    State("shift-starts", "value"),
    State("shift-length", "value"),
    State("daily-budget", "value"),
    State("hourly-wage", "value"),
    State("handle-time", "value"),
    State("occupancy", "value"),
    State("max-calls-shift", "value"),
    State("min-calls-shift", "value"),
    prevent_initial_call=True,
)
def solve_scenario(
    _clicks,
    history_records,
    roster,
    target_date,
    borough,
    calls_per_request,
    available_agents,
    shift_starts,
    shift_length,
    daily_budget,
    hourly_wage,
    handle_time,
    occupancy,
    max_calls_shift,
    min_calls_shift,
):
    history = pd.DataFrame.from_records(history_records)
    if not shift_starts:
        raise ValueError("Select at least one eligible shift start.")
    hourly_capacity = 60 / float(handle_time) * (float(occupancy) / 100)
    demand, metrics = forecast_hourly_demand(
        history,
        target_date,
        borough,
        calls_per_request=float(calls_per_request),
    )
    solution = optimize_hourly_staffing(
        demand,
        available_agents=int(available_agents),
        shift_starts=shift_starts,
        shift_length=int(shift_length),
        hourly_capacity=hourly_capacity,
        break_hour_offset=int(shift_length) // 2,
        break_capacity_factor=0.5,
        max_calls_per_shift=int(max_calls_shift),
        min_calls_per_shift=int(min_calls_shift),
        hourly_wage=float(hourly_wage),
        daily_budget=float(daily_budget),
        roster=roster,
    )
    display = demand.merge(
        solution.hourly,
        on=["hour", "forecast_calls"],
        validate="one_to_one",
    )
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=display["hour"],
            y=display["forecast_calls"],
            name="Forecast call demand",
            marker_color="#9ca3af",
        )
    )
    figure.add_trace(
        go.Bar(
            x=display["hour"],
            y=display["calls_served"],
            name="Calls allocated/served",
            marker_color="#0c7c86",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=display["hour"],
            y=display["unmet_calls"],
            name="Unserved calls / service shortfall",
            mode="lines+markers",
            line={"color": "#cc4b37", "width": 3},
            yaxis="y2",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=display["hour"],
            y=display["staffed_agents"],
            name="Scheduled agents",
            mode="lines",
            line={"color": "#5846a8", "width": 2, "dash": "dash"},
            yaxis="y2",
        )
    )
    figure.update_layout(
        template="plotly_white",
        barmode="group",
        height=460,
        title=f"Hourly call scenario for {target_date} — {borough}",
        xaxis={"title": "Hour of day", "tickmode": "linear", "dtick": 1},
        yaxis={"title": "Calls"},
        yaxis2={"title": "Unserved calls / agents", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "y": -0.25},
        margin={"b": 100},
    )
    validation_status = (
        f"Rolling-origin same-weekday baseline validation over {int(metrics['validation_observations'])} "
        f"hourly observations: MAE {metrics['validation_mae']:.2f} calls/hour, "
        f"RMSE {metrics['validation_rmse']:.2f}. Forecast is derived from current request timestamps "
        f"and the configured {float(calls_per_request):.1%} request-to-call scenario factor."
    )
    kpis = [
        html.Div([html.Small("Selected shifts"), html.H3(f"{len(solution.assignments):,}")], style=CARD_STYLE),
        html.Div([html.Small("Staffing spend"), html.H3(f"${solution.total_cost:,.0f}")], style=CARD_STYLE),
        html.Div([html.Small("Budget remaining"), html.H3(f"${solution.budget_remaining:,.0f}")], style=CARD_STYLE),
        html.Div([html.Small("Unserved calls"), html.H3(f"{solution.unmet_calls:,}")], style=CARD_STYLE),
        html.Div([html.Small("Solver status"), html.H3(solution.solver_status)], style={**CARD_STYLE, "maxWidth": "480px"}),
    ]
    schedule = (
        _make_table(solution.assignments.round({"shift_cost": 2}))
        if not solution.assignments.empty
        else html.P("No shifts selected under the current budget and service-shortfall objective.")
    )
    hourly_table = _make_table(
        solution.hourly.assign(
            hour=solution.hourly["hour"].map(lambda hour: f"{hour:02d}:00")
        ).round({"handling_capacity": 1})
    )
    return figure, validation_status, kpis, schedule, hourly_table


if __name__ == "__main__":
    app.run(
        debug=os.getenv("DASH_DEBUG", "0") == "1",
        host=os.getenv("DASH_HOST", "127.0.0.1"),
        port=int(os.getenv("WORKFORCE_DASH_PORT", "8051")),
    )
