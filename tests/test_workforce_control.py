import numpy as np
import pandas as pd
import pytest

from workforce_control import forecast_control_demand


def make_request_history(days: int = 100) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    return pd.DataFrame(
        [
            {
                "day": day,
                "hour": hour,
                "borough": borough,
                "requests": 10 + hour + 2 * (index // 7) + borough_index,
            }
            for index, day in enumerate(dates)
            for borough_index, borough in enumerate(("BRONX", "QUEENS"))
            for hour in range(24)
        ]
    )


def test_forecast_uses_recent_same_weekday_percentile_and_scales_calls():
    history = make_request_history()
    target = history.day.max() + pd.Timedelta(days=1)
    forecast, metrics = forecast_control_demand(
        history,
        target,
        "BRONX",
        history_days=56,
        percentile=0.75,
        calls_per_request=0.1,
    )
    matrix = history.query("borough == 'BRONX'").pivot(
        index="day", columns="hour", values="requests"
    )
    sample = matrix.loc[
        (matrix.index < target)
        & (matrix.index >= target - pd.Timedelta(days=56))
        & (matrix.index.dayofweek == target.dayofweek)
    ]

    expected_requests = np.rint(np.quantile(sample.to_numpy(), 0.75, axis=0)).astype(int)
    expected_calls = np.rint(expected_requests * 0.1).astype(int)
    assert forecast.hour.tolist() == list(range(24))
    assert forecast.forecast_requests_proxy.tolist() == expected_requests.tolist()
    assert forecast.forecast_calls.tolist() == expected_calls.tolist()
    assert metrics["validation_observations"] > 24
    assert np.isfinite(metrics["validation_mae"])


def test_forecast_combines_boroughs_and_fills_missing_hours():
    history = make_request_history()
    history = history.loc[history.hour != 0]
    target = history.day.max() + pd.Timedelta(days=1)
    forecast, _ = forecast_control_demand(history, target, "ALL", calls_per_request=1)

    assert forecast.loc[forecast.hour == 0, "forecast_requests_proxy"].item() == 0
    assert forecast.loc[forecast.hour == 1, "forecast_requests_proxy"].item() > 0


def test_forecast_rejects_invalid_dates_data_and_assumptions():
    history = make_request_history()
    latest = history.day.max()

    with pytest.raises(ValueError, match="after the latest observed"):
        forecast_control_demand(history, latest)
    with pytest.raises(ValueError, match="No recent"):
        forecast_control_demand(history, latest + pd.Timedelta(days=1), "MANHATTAN")
    with pytest.raises(ValueError, match="percentile"):
        forecast_control_demand(
            history,
            latest + pd.Timedelta(days=1),
            percentile=0.4,
        )
