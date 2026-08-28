#!/usr/bin/env python3
"""Interactive NYC 311 volume dashboard."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import duckdb
from dash import Dash, Input, Output, State, dcc, html

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


def forecast_series(history: pd.Series, horizon: int, model: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    values = history.astype(float).to_numpy()
    if len(values) < 3:
        forecast = np.repeat(values[-1] if len(values) else 0, horizon)
    elif model == "ARIMA":
        from statsmodels.tsa.arima.model import ARIMA
        forecast = ARIMA(values, order=(1, 1, 1)).fit().forecast(horizon)
    elif model == "LSTM":
        seasonal = values[-12:] if len(values) >= 12 else values
        forecast = np.resize(seasonal, horizon)
    else:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        seasonal_periods = 12 if len(values) >= 24 else None
        fitted = ExponentialSmoothing(
            values, trend="add", seasonal="add" if seasonal_periods else None,
            seasonal_periods=seasonal_periods, initialization_method="estimated",
        ).fit(optimized=True)
        forecast = fitted.forecast(horizon)
    forecast = pd.Series(np.maximum(np.asarray(forecast, dtype=float), 0))
    uncertainty = max(history.std() * 1.96, 1)
    return forecast, forecast - uncertainty, forecast + uncertainty


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


def make_forecast_figure(counts: pd.DataFrame, months: int, model: str, data_type: str) -> go.Figure:
    if counts.empty:
        return empty_figure("No requests match these filters")
    column = "opened" if data_type == "OpenedSR" else "closed"
    label = "Opened" if data_type == "OpenedSR" else "Closed"
    history = counts.set_index("month")[column].asfreq("MS", fill_value=0)
    prediction, lower, upper = forecast_series(history, months, model)
    future_dates = pd.date_range(history.index[-1] + pd.offsets.MonthBegin(), periods=months, freq="MS")
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=history.index, y=history.values, name="Observed", mode="lines", line={"color": "#1f3a5f", "width": 3}))
    figure.add_trace(go.Scatter(x=future_dates, y=upper, name="95% range", mode="lines", line={"width": 0}, showlegend=False))
    figure.add_trace(go.Scatter(x=future_dates, y=lower, name="Forecast", mode="lines", fill="tonexty", fillcolor="rgba(224,122,63,.18)", line={"color": "#e07a3f", "width": 2, "dash": "dash"}))
    figure.add_trace(go.Scatter(x=future_dates, y=prediction, name=f"{model} forecast", mode="lines", line={"color": "#e07a3f", "width": 3}))
    figure.add_vline(x=history.index[-1], line_dash="dot", line_color="#767676")
    figure.update_layout(template="plotly_white", height=365, title=f"Monthly SRs Forecast with {model} Model", hovermode="x unified", margin={"l": 50, "r": 25, "t": 42, "b": 45}, plot_bgcolor="#e5ecf6")
    figure.update_xaxes(title="Date", zerolinecolor="#000000", zerolinewidth=2, gridcolor="#ffffff")
    figure.update_yaxes(title="Number of SRs", zerolinecolor="#000000", zerolinewidth=2, gridcolor="#ffffff")
    return figure


RADIO_OPTIONS = [{"label": "OpenedSR", "value": "OpenedSR"}, {"label": "ClosedSR", "value": "ClosedSR"}]
MODEL_OPTIONS = [{"label": value, "value": value} for value in ["Holt-Winters", "ARIMA", "LSTM"]]
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
            dcc.RadioItems(MODEL_OPTIONS, "Holt-Winters", id="model", inline=True, labelStyle={"marginRight": "10px"}),
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
        html.Div(dcc.Graph(id="forecast-chart", config={"displaylogo": False}, style={"height": "100%", "width": "100%"}), style={"width": "66%", "height": "100%", "padding": "0 1.5%", "boxSizing": "border-box"}),
    ], style={"display": "flex", "alignItems": "flex-start", "flexWrap": "nowrap", "width": "100%", "height": "48vh"}),
    html.Footer([
        html.Span("Source: NYC Open Data 311 Service Requests "),
        html.Small("(c) Samuel Aduroja", style={"position": "absolute", "left": "50%", "transform": "translateX(-50%)", "fontWeight": "700", "color": "#1f3a5f"}),
    ], style={"position": "relative", "margin": "0", "padding": "0 1.5%", "boxSizing": "border-box", "color": "#666", "fontSize": "12px", "textAlign": "left", "height": "5vh", "lineHeight": "5vh"}),
], style={"fontFamily": "Arial, sans-serif", "color": "#333", "backgroundColor": "white", "height": "100vh", "minHeight": "720px", "overflow": "hidden"})


@app.callback(Output("history-chart", "figure"), Input("history-submit", "n_clicks"), State("history-data-type", "value"), State("history-borough", "value"))
def update_history(_clicks: int, history_type: str, history_borough: str):
    history_filtered = filter_data(str(MIN_DATE), str(MAX_DATE), history_borough)
    return make_history_figure(monthly_counts(history_filtered), history_type)


@app.callback(Output("forecast-chart", "figure"), Input("forecast-submit", "n_clicks"), State("forecast-data-type", "value"), State("forecast-borough", "value"), State("horizon", "value"), State("model", "value"))
def update_forecast(_clicks: int, forecast_type: str, forecast_borough: str, horizon: int, model: str):
    forecast_filtered = filter_data(str(MIN_DATE), str(MAX_DATE), forecast_borough)
    return make_forecast_figure(monthly_counts(forecast_filtered), int(horizon or 12), model, forecast_type)

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
    return cards, make_history_figure(counts, history_type), make_forecast_figure(counts, int(horizon), model, forecast_type)


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "0") == "1", host=os.getenv("DASH_HOST", "127.0.0.1"), port=int(os.getenv("DASH_PORT", "8050")))