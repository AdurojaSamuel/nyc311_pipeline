#!/usr/bin/env python3
"""Interactive NYC 311 volume dashboard."""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html

from forecasting import train_forecast
from nyc311_data import refresh_dashboard_data
from workforce import optimize_staffing

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.getenv("NYC311_DATA_ROOT", ROOT / "data"))
CURATED = DATA_ROOT / "curated"


def load_data() -> pd.DataFrame:
    """
    Load the compact dashboard dataset when available.

    Falls back to the full curated Parquet data lake for local
    development if dashboard_data.parquet does not exist.
    """

    dashboard_file = DATA_ROOT / "dashboard_data.parquet"

    # Preferred path for deployment.
    if dashboard_file.exists():
        print(f"Loading dashboard data from: {dashboard_file}")

        frame = pd.read_parquet(dashboard_file)

        frame["date"] = pd.to_datetime(frame["date"])
        frame, source_updated = refresh_dashboard_data(frame)
        print(f"NYC Open Data refreshed through: {source_updated}")

        return (
            frame
            .sort_values(["date", "borough"])
            .reset_index(drop=True)
        )

    # Fallback to the full Parquet data lake.
    parquet_glob = str(
        CURATED / "created_year=*" / "created_month=*" / "*.parquet"
    )

    if not list(
        CURATED.glob("created_year=*/created_month=*/*.parquet")
    ):
        raise FileNotFoundError(
            f"No dashboard_data.parquet or curated Parquet files "
            f"found under {DATA_ROOT}"
        )

    query = """
        WITH bounds AS (
            SELECT
                min(CAST(created_date AS DATE)) AS min_date,
                max(CAST(created_date AS DATE)) AS max_date
            FROM read_parquet(?, union_by_name=true)
        ),

        events AS (
            SELECT
                CAST(created_date AS DATE) AS date,
                upper(
                    coalesce(
                        nullif(trim(borough), ''),
                        'UNKNOWN'
                    )
                ) AS borough,
                count(DISTINCT unique_key) AS opened,
                0::BIGINT AS closed
            FROM read_parquet(?, union_by_name=true)
            WHERE created_date IS NOT NULL
            GROUP BY 1, 2

            UNION ALL

            SELECT
                CAST(closed_date AS DATE) AS date,
                upper(
                    coalesce(
                        nullif(trim(borough), ''),
                        'UNKNOWN'
                    )
                ) AS borough,
                0::BIGINT AS opened,
                count(DISTINCT unique_key) AS closed
            FROM read_parquet(?, union_by_name=true)
            CROSS JOIN bounds
            WHERE closed_date IS NOT NULL
              AND CAST(closed_date AS DATE)
                  BETWEEN bounds.min_date AND bounds.max_date
            GROUP BY 1, 2
        )

        SELECT
            date,
            borough,
            sum(opened)::BIGINT AS opened,
            sum(closed)::BIGINT AS closed
        FROM events
        GROUP BY 1, 2
        ORDER BY 1, 2
    """

    with duckdb.connect() as connection:
        frame = connection.execute(
            query,
            [parquet_glob, parquet_glob, parquet_glob],
        ).df()

    frame["date"] = pd.to_datetime(frame["date"])
    frame, source_updated = refresh_dashboard_data(frame)
    print(f"NYC Open Data refreshed through: {source_updated}")

    return (
        frame
        .sort_values(["date", "borough"])
        .reset_index(drop=True)
    )


DATA = load_data()
MIN_DATE = DATA["date"].min().date()
MAX_DATE = DATA["date"].max().date()
BOROUGHS = ["ALL", "BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND", "UNKNOWN", "UNSPECIFIED"]


def empty_figure(message: str) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, x=0.5, y=0.5, showarrow=False, font={"size": 16})
    figure.update_layout(template="plotly_white", height=420)
    return figure


def filter_data(start: str, end: str, borough: str) -> pd.DataFrame:
    end_date = pd.Timestamp(end) + pd.Timedelta(days=1)
    filtered = DATA[(DATA["date"] >= pd.Timestamp(start)) & (DATA["date"] < end_date)]
    if borough != "ALL":
        filtered = filtered[filtered["borough"] == borough]
    return filtered


def monthly_counts(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["month", "opened", "closed"])
    result = frame.assign(month=frame["date"].dt.to_period("M").dt.to_timestamp())
    return result.groupby("month", as_index=False)[["opened", "closed"]].sum()


def make_history_figure(counts: pd.DataFrame, data_type: str) -> go.Figure:
    if counts.empty:
        return empty_figure("No requests match these filters")
    figure = go.Figure()
    label = "Opened" if data_type == "OpenedSR" else "Closed"
    column = "opened" if data_type == "OpenedSR" else "closed"
    figure.add_trace(go.Scatter(x=counts["month"], y=counts[column], name=label, mode="lines", line={"color": "#0c7c86", "width": 3}))
    figure.update_layout(template="plotly_white", height=305, title="NYC311 Service Requests(SRs)", hovermode="x unified", margin={"l": 50, "r": 25, "t": 42, "b": 45}, plot_bgcolor="#e5ecf6")
    figure.update_xaxes(title="Date", zerolinecolor="#ffffff", zerolinewidth=2, gridcolor="#ffffff")
    figure.update_yaxes(title="Number of SRs", zerolinecolor="#ffffff", zerolinewidth=2, gridcolor="#ffffff")
    return figure


def make_forecast_figure(counts: pd.DataFrame, months: int, model: str, data_type: str) -> tuple[go.Figure, str]:
    if counts.empty:
        return empty_figure("No requests match these filters"), ""
    column = "opened" if data_type == "OpenedSR" else "closed"
    history = counts.set_index("month")[column].asfreq("MS", fill_value=0)
    result = train_forecast(history, months, model)
    prediction, lower, upper = result.forecast, result.lower, result.upper
    future_dates = pd.date_range(history.index[-1] + pd.offsets.MonthBegin(), periods=months, freq="MS")
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=history.index, y=history.values, name="Observed", mode="lines", line={"color": "#1f3a5f", "width": 3}))
    figure.add_trace(go.Scatter(x=future_dates, y=upper, name="Approximate range", mode="lines", line={"width": 0}, showlegend=False))
    figure.add_trace(go.Scatter(x=future_dates, y=lower, name="Forecast range", mode="lines", fill="tonexty", fillcolor="rgba(224,122,63,.18)", line={"color": "#e07a3f", "width": 2, "dash": "dash"}))
    figure.add_trace(go.Scatter(x=future_dates, y=prediction, name=f"{result.model} forecast", mode="lines", line={"color": "#e07a3f", "width": 3}))
    figure.add_vline(x=history.index[-1], line_dash="dot", line_color="#767676")
    figure.update_layout(template="plotly_white", height=365, title=f"Monthly SRs Forecast with {result.model} Model", hovermode="x unified", margin={"l": 50, "r": 25, "t": 42, "b": 45}, plot_bgcolor="#e5ecf6")
    figure.update_xaxes(title="Date", zerolinecolor="#000000", zerolinewidth=2, gridcolor="#ffffff")
    figure.update_yaxes(title="Number of SRs", zerolinecolor="#000000", zerolinewidth=2, gridcolor="#ffffff")
    summary = (
        f"Selected {result.model}; holdout MAE {result.validation_mae:,.1f}. "
        f"MLflow run: {result.best_run_id}."
    )
    return figure, summary


RADIO_OPTIONS = [{"label": "OpenedSR", "value": "OpenedSR"}, {"label": "ClosedSR", "value": "ClosedSR"}]
MODEL_OPTIONS = [{"label": value, "value": value} for value in ["Best", "Holt-Winters", "AutoARIMA", "LSTM"]]
CONTROL_STYLE = {"backgroundColor": "#f5f5f5", "border": "1px solid #ddd", "borderRadius": "4px", "padding": "16px", "minHeight": "214px"}
LABEL_STYLE = {"display": "block", "fontWeight": "700", "fontSize": "13px", "marginBottom": "10px"}
RADIO_STYLE = {"display": "flex", "gap": "12px", "fontSize": "13px"}
BUTTON_STYLE = {"backgroundColor": "#337ab7", "border": "0", "borderRadius": "4px", "color": "white", "padding": "7px 14px", "fontSize": "13px", "marginTop": "18px"}

def control_panel(data_type_id: str, borough_id: str, button_id: str, include_forecast: bool = False):
    controls = [
        html.Label("Data type", style=LABEL_STYLE),
        dcc.RadioItems(RADIO_OPTIONS, "OpenedSR", id=data_type_id, inline=True, labelStyle={"marginRight": "12px"}),
        html.Hr(),
        html.Label("Select Borough", style=LABEL_STYLE),
        dcc.Dropdown(BOROUGHS, "ALL", id=borough_id, clearable=False, style={"fontSize": "13px"}),
        html.Hr(),
    ]
    if include_forecast:
        controls.extend([
            html.Label("Months to predict", style=LABEL_STYLE),
            dcc.Input(id="horizon", type="number", min=1, max=60, step=1, value=12, style={"width": "100%", "padding": "7px", "border": "1px solid #ccc", "borderRadius": "4px"}),
            html.Label("Model type", style={**LABEL_STYLE, "marginTop": "18px"}),
            dcc.RadioItems(MODEL_OPTIONS, "Best", id="model", inline=True, labelStyle={"marginRight": "10px"}),
        ])
    controls.append(html.Button("view", id=button_id, n_clicks=0, style=BUTTON_STYLE))
    return html.Div(controls, style=CONTROL_STYLE)

app = Dash(__name__, title="Opened and Closed Service Requests")
server = app.server
app.layout = html.Div([
    html.H4("Opened and Closed Service Requests", style={"fontWeight": "400", "margin": "6px 1.5% 8px"}),
    html.Div([
        html.Div(control_panel("history-data-type", "history-borough", "history-submit"), style={"width": "34%", "padding": "0 1.5%", "boxSizing": "border-box"}),
        html.Div(dcc.Graph(id="history-chart", config={"displaylogo": False}, style={"height": "100%", "width": "100%"}), style={"width": "66%", "height": "100%", "padding": "0 1.5%", "boxSizing": "border-box"}),
    ], style={"display": "flex", "alignItems": "flex-start", "flexWrap": "nowrap", "width": "100%", "height": "38vh"}),
    html.Hr(style={"border": "0", "borderTop": "1px solid orange", "margin": "18px 1.5% 14px"}),
    html.H4("Projecting Future Requests: Opened and Closed", style={"fontWeight": "400", "margin": "0 1.5% 8px"}),
    html.Div([
        html.Div(control_panel("forecast-data-type", "forecast-borough", "forecast-submit", include_forecast=True), style={"width": "34%", "padding": "0 1.5%", "boxSizing": "border-box"}),
        html.Div([
            dcc.Graph(id="forecast-chart", config={"displaylogo": False}, style={"height": "90%", "width": "100%"}),
            html.Div(id="forecast-status", style={"fontSize": "12px", "color": "#555", "padding": "0 8px"}),
        ], style={"width": "66%", "height": "100%", "padding": "0 1.5%", "boxSizing": "border-box"}),
    ], style={"display": "flex", "alignItems": "flex-start", "flexWrap": "nowrap", "width": "100%", "height": "48vh"}),
    html.Hr(style={"border": "0", "borderTop": "1px solid orange", "margin": "18px 1.5% 14px"}),
    html.H4("Call-Taker Staffing and Labor-Cost Optimization", style={"fontWeight": "400", "margin": "0 1.5% 8px"}),
    html.P(
        "Planning estimate based on forecast requests treated as calls. Adjust the assumptions; Erlang-C "
        "finds the lowest staffing level that meets the selected service target and occupancy limit.",
        style={"margin": "0 1.5% 12px", "color": "#555"},
    ),
    html.Div([
        html.Div([
            html.Label("Borough", style=LABEL_STYLE),
            dcc.Dropdown(BOROUGHS, "ALL", id="staffing-borough", clearable=False),
            html.Label("Forecast model", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Dropdown(MODEL_OPTIONS, "Best", id="staffing-model", clearable=False),
            html.Label("Months to plan", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="staffing-horizon", type="number", min=1, max=60, step=1, value=12),
            html.Label("Calls per service request", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="calls-per-request", type="number", min=0, step=0.1, value=1.0),
            html.Label("Average handle time (minutes)", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="handle-time", type="number", min=1, step=1, value=8),
            html.Label("Operating hours per day", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="operating-hours", type="number", min=1, max=24, step=1, value=8),
            html.Label("Business days per month", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="business-days", type="number", min=1, max=31, step=1, value=22),
            html.Label("Hourly wage ($)", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="hourly-wage", type="number", min=0, step=1, value=25),
            html.Label("Paid shrinkage (%)", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="shrinkage", type="number", min=0, max=99, step=1, value=30),
            html.Label("Service-level target (%)", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="service-target", type="number", min=1, max=99, step=1, value=80),
            html.Label("Answer target (seconds)", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="answer-seconds", type="number", min=0, step=1, value=20),
            html.Label("Occupancy limit (%)", style={**LABEL_STYLE, "marginTop": "12px"}),
            dcc.Input(id="occupancy-limit", type="number", min=1, max=100, step=1, value=85),
            html.Button("Optimize staffing", id="staffing-submit", n_clicks=0, style=BUTTON_STYLE),
        ], style={**CONTROL_STYLE, "width": "30%", "boxSizing": "border-box"}),
        html.Div([
            dcc.Graph(id="staffing-chart", config={"displaylogo": False}),
            html.Div(id="staffing-summary", style={"fontSize": "14px", "padding": "8px"}),
        ], style={"width": "70%", "boxSizing": "border-box"}),
    ], style={"display": "flex", "alignItems": "flex-start", "gap": "12px", "margin": "0 1.5% 24px"}),
    html.Footer([
        html.Span(f"Source: NYC Open Data 311 Service Requests; current through {MAX_DATE} "),
        html.Small("(c) Samuel Aduroja", style={"position": "absolute", "left": "50%", "transform": "translateX(-50%)", "fontWeight": "700", "color": "#1f3a5f"}),
    ], style={"position": "relative", "margin": "0", "padding": "0 1.5%", "boxSizing": "border-box", "color": "#666", "fontSize": "12px", "textAlign": "left", "height": "5vh", "lineHeight": "5vh"}),
], style={"fontFamily": "Arial, sans-serif", "color": "#333", "backgroundColor": "white", "minHeight": "100vh", "overflowY": "auto"})


@app.callback(Output("history-chart", "figure"), Input("history-submit", "n_clicks"), State("history-data-type", "value"), State("history-borough", "value"))
def update_history(_clicks: int, history_type: str, history_borough: str):
    history_filtered = filter_data(str(MIN_DATE), str(MAX_DATE), history_borough)
    return make_history_figure(monthly_counts(history_filtered), history_type)


@app.callback(Output("forecast-chart", "figure"), Output("forecast-status", "children"), Input("forecast-submit", "n_clicks"), State("forecast-data-type", "value"), State("forecast-borough", "value"), State("horizon", "value"), State("model", "value"))
def update_forecast(_clicks: int, forecast_type: str, forecast_borough: str, horizon: int, model: str):
    forecast_filtered = filter_data(str(MIN_DATE), str(MAX_DATE), forecast_borough)
    return make_forecast_figure(monthly_counts(forecast_filtered), int(horizon or 12), model, forecast_type)


@app.callback(
    Output("staffing-chart", "figure"),
    Output("staffing-summary", "children"),
    Input("staffing-submit", "n_clicks"),
    State("staffing-borough", "value"),
    State("staffing-model", "value"),
    State("calls-per-request", "value"),
    State("handle-time", "value"),
    State("operating-hours", "value"),
    State("business-days", "value"),
    State("hourly-wage", "value"),
    State("shrinkage", "value"),
    State("service-target", "value"),
    State("answer-seconds", "value"),
    State("occupancy-limit", "value"),
    State("staffing-horizon", "value"),
)
def update_staffing(
    _clicks,
    borough,
    model,
    calls_per_request,
    handle_time,
    operating_hours,
    business_days,
    hourly_wage,
    shrinkage,
    service_target,
    answer_seconds,
    occupancy_limit,
    horizon,
):
    filtered = filter_data(str(MIN_DATE), str(MAX_DATE), borough)
    counts = monthly_counts(filtered)
    if counts.empty:
        return empty_figure("No requests match these filters"), "No forecast available for this selection."
    history = counts.set_index("month")["opened"].asfreq("MS", fill_value=0)
    forecast = train_forecast(history, int(horizon or 12), model)
    staffing = optimize_staffing(
        forecast.forecast,
        calls_per_request=float(calls_per_request),
        handle_time_minutes=float(handle_time),
        operating_hours_per_day=float(operating_hours),
        business_days_per_month=int(business_days),
        hourly_wage=float(hourly_wage),
        shrinkage=float(shrinkage) / 100,
        service_level_target=float(service_target) / 100,
        answer_seconds=float(answer_seconds),
        occupancy_limit=float(occupancy_limit) / 100,
    )
    months = pd.date_range(history.index[-1] + pd.offsets.MonthBegin(), periods=len(staffing), freq="MS")
    figure = go.Figure()
    figure.add_trace(go.Bar(x=months, y=staffing["fixed_monthly_cost"], name="Fixed peak staffing baseline", marker_color="#9ca3af"))
    figure.add_trace(go.Bar(x=months, y=staffing["monthly_labor_cost"], name="Forecast-optimized labor cost", marker_color="#0c7c86"))
    figure.update_layout(
        template="plotly_white",
        barmode="group",
        height=420,
        title="Monthly labor cost at forecast-driven staffing",
        yaxis_title="Estimated monthly labor cost ($)",
        legend={"orientation": "h", "y": -0.2},
    )
    total_savings = float(staffing["monthly_savings"].sum())
    return figure, (
        f"Selected forecast: {forecast.model} (holdout MAE {forecast.validation_mae:,.1f}; "
        f"MLflow run {forecast.best_run_id}). Recommended call-takers: "
        f"{int(staffing.call_takers.min())}–{int(staffing.call_takers.max())} across the horizon. "
        f"Modeled service level is at least {staffing.service_level.min() * 100:.1f}% with peak occupancy "
        f"{staffing.occupancy.max() * 100:.1f}%. "
        f"Estimated savings versus fixed peak staffing: ${total_savings:,.0f}. "
        "Planning estimate only; actual schedules must account for intraday peaks, breaks, and labor rules."
    )


def update_dashboard_legacy(start: str, end: str, borough: str, history_type: str, forecast_type: str, horizon: int, model: str):
    filtered = filter_data(start, end, borough)
    counts = monthly_counts(filtered)
    history_column = "opened" if history_type == "OpenedSR" else "closed"
    forecast_column = "opened" if forecast_type == "OpenedSR" else "closed"
    history_label = "opened" if history_type == "OpenedSR" else "closed"
    forecast_label = "opened" if forecast_type == "OpenedSR" else "closed"
    history_total = int(filtered[history_column].sum())
    forecast_total = int(filtered[forecast_column].sum())
    cards = [
        html.Div([html.Span(f"{history_label.title()} requests"), html.Strong(f"{history_total:,}"), html.Small("in selected window")], className="kpi"),
        html.Div([html.Span(f"{forecast_label.title()} requests"), html.Strong(f"{forecast_total:,}"), html.Small("used for forecast")], className="kpi"),
        html.Div([html.Span("Borough scope"), html.Strong(borough.title() if borough != "ALL" else "All five"), html.Small("selected geography")], className="kpi accent"),
    ]
    return cards, make_history_figure(counts, history_type), make_forecast_figure(counts, int(horizon), model, forecast_type)[0]


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "0") == "1", host=os.getenv("DASH_HOST", "127.0.0.1"), port=int(os.getenv("DASH_PORT", "8050")))