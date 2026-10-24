"""Demand preparation for the supervisor-oriented workforce control dashboard."""

from __future__ import annotations

import numpy as np
import pandas as pd


def forecast_control_demand(
    history: pd.DataFrame,
    target_date: str | pd.Timestamp,
    borough: str = "ALL",
    *,
    history_days: int = 56,
    percentile: float = 0.75,
    calls_per_request: float = 0.05,
    backtest_days: int = 28,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Forecast request proxies by weekday/hour and scale them into a call scenario."""
    required = {"day", "hour", "borough", "requests"}
    missing = required.difference(history.columns)
    if missing:
        raise ValueError(
            f"Hourly request history is missing columns: {', '.join(sorted(missing))}."
        )
    if history.empty:
        raise ValueError("Hourly request history is empty.")
    if history_days < 14 or backtest_days < 1:
        raise ValueError(
            "History must cover at least 14 days and backtest length must be positive."
        )
    if not np.isfinite(percentile) or not 0.5 <= percentile <= 0.99:
        raise ValueError("Forecast percentile must be between 0.50 and 0.99.")
    if not np.isfinite(calls_per_request) or calls_per_request < 0:
        raise ValueError("Calls per service request must be finite and non-negative.")

    target = pd.Timestamp(target_date).normalize()
    frame = history.loc[:, ["day", "hour", "borough", "requests"]].copy()
    frame["day"] = pd.to_datetime(frame["day"], errors="raise").dt.normalize()
    frame["hour"] = pd.to_numeric(frame["hour"], errors="raise")
    frame["requests"] = pd.to_numeric(frame["requests"], errors="raise")
    if (
        not frame["hour"].between(0, 23).all()
        or not np.isfinite(frame["hour"]).all()
        or not np.isfinite(frame["requests"]).all()
        or (frame["requests"] < 0).any()
    ):
        raise ValueError("Hourly history must contain valid hours and finite, non-negative counts.")
    frame["hour"] = frame["hour"].astype(int)
    frame["borough"] = frame["borough"].fillna("").astype(str).str.strip().str.upper()
    if borough != "ALL":
        frame = frame.loc[frame["borough"] == borough.upper()]
    if frame.empty:
        raise ValueError(f"No recent NYC 311 request data exists for {borough}.")
    if target <= frame["day"].max():
        raise ValueError("Plan date must be after the latest observed request date.")

    hourly = frame.groupby(["day", "hour"], as_index=False)["requests"].sum()
    calendar = pd.date_range(hourly["day"].min(), hourly["day"].max(), freq="D")
    matrix = (
        hourly.pivot(index="day", columns="hour", values="requests")
        .reindex(index=calendar, columns=range(24), fill_value=0)
        .fillna(0)
    )

    def predict(day: pd.Timestamp) -> np.ndarray:
        sample = matrix.loc[
            (matrix.index < day)
            & (matrix.index >= day - pd.Timedelta(days=history_days))
            & (matrix.index.dayofweek == day.dayofweek)
        ]
        if len(sample) < 4:
            raise ValueError(
                f"At least four prior matching weekdays are required to forecast {day.date()}."
            )
        return np.quantile(sample.to_numpy(dtype=float), percentile, axis=0)

    request_forecast = np.maximum(np.rint(predict(target)), 0).astype(int)
    calls_forecast = np.maximum(np.rint(request_forecast * calls_per_request), 0).astype(int)

    validation_dates = matrix.index[
        matrix.index >= matrix.index.max() - pd.Timedelta(days=backtest_days - 1)
    ]
    errors: list[float] = []
    for day in validation_dates:
        try:
            expected = predict(day) * calls_per_request
        except ValueError:
            continue
        actual = matrix.loc[day].to_numpy(dtype=float) * calls_per_request
        errors.extend((actual - expected).tolist())
    if not errors:
        raise ValueError("Not enough history is available for rolling-origin forecast validation.")

    forecast = pd.DataFrame(
        {
            "hour": np.arange(24),
            "forecast_requests_proxy": request_forecast,
            "forecast_calls": calls_forecast,
        }
    )
    errors_array = np.asarray(errors, dtype=float)
    metrics = {
        "validation_mae": float(np.mean(np.abs(errors_array))),
        "validation_rmse": float(np.sqrt(np.mean(np.square(errors_array)))),
        "validation_observations": float(len(errors_array)),
        "forecast_requests_proxy": float(request_forecast.sum()),
        "forecast_calls": float(calls_forecast.sum()),
    }
    return forecast, metrics
