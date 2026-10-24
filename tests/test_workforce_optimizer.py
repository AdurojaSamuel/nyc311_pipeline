import base64

import numpy as np
import pandas as pd
import pytest

from workforce_optimizer import (
    forecast_hourly_demand,
    optimize_hourly_staffing,
    parse_agent_roster,
)


def make_hourly_history(days: int = 70) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    return pd.DataFrame(
        [
            {
                "day": day,
                "hour": hour,
                "borough": "BRONX",
                "requests": 10 + hour + day.dayofweek,
            }
            for day in dates
            for hour in range(24)
        ]
    )


def test_recent_weekday_hourly_forecast_uses_rolling_validation():
    history = make_hourly_history()
    forecast, metrics = forecast_hourly_demand(
        history,
        pd.Timestamp(history.day.max()) + pd.Timedelta(days=1),
        "BRONX",
        calls_per_request=0.1,
    )

    assert len(forecast) == 24
    assert forecast.hour.tolist() == list(range(24))
    assert (forecast.forecast_calls >= 0).all()
    assert (forecast.forecast_requests_proxy >= forecast.forecast_calls).all()
    assert metrics["validation_observations"] > 24
    assert np.isfinite(metrics["validation_mae"])


def test_milp_minimizes_unserved_calls_then_shift_cost():
    solution = optimize_hourly_staffing(
        np.full(24, 2),
        available_agents=3,
        shift_starts=[0, 8, 16],
        shift_length=8,
        hourly_capacity=4,
        break_hour_offset=4,
        break_capacity_factor=0.5,
        max_calls_per_shift=48,
        hourly_wage=25,
        daily_budget=600,
    )

    assert solution.unmet_calls == 0
    assert solution.total_cost == 600
    assert solution.budget_remaining == 0
    assert len(solution.assignments) == 3
    assert solution.hourly.calls_served.sum() == 48
    assert solution.hourly.unmet_calls.sum() == 0
    assert solution.solver_status


def test_milp_respects_budget_and_per_shift_minimum():
    solution = optimize_hourly_staffing(
        np.full(24, 4),
        available_agents=3,
        shift_starts=[0, 8, 16],
        hourly_capacity=4,
        max_calls_per_shift=48,
        min_calls_per_shift=12,
        hourly_wage=25,
        daily_budget=400,
    )

    assert solution.total_cost <= 400
    assert solution.budget_remaining >= 0
    assert solution.unmet_calls > 0
    assert (solution.assignments.calls_assigned >= 12).all()


def test_roster_upload_parses_individual_eligibility_and_limits():
    csv = (
        "agent_id,eligible_shifts,hourly_wage,max_calls_per_shift,min_calls_per_shift\n"
        "A1,\"0,8\",30,40,5\n"
    )
    contents = "data:text/csv;base64," + base64.b64encode(csv.encode()).decode()

    assert parse_agent_roster(contents) == [
        {
            "agent_id": "A1",
            "eligible_shifts": [0, 8],
            "hourly_wage": 30.0,
            "max_calls_per_shift": 40,
            "min_calls_per_shift": 5,
        }
    ]


def test_roster_limits_apply_to_each_agent_and_shift_eligibility():
    roster = [
        {
            "agent_id": "A1",
            "eligible_shifts": [0],
            "hourly_wage": 30,
            "max_calls_per_shift": 40,
            "min_calls_per_shift": 5,
        },
        {
            "agent_id": "A2",
            "eligible_shifts": [8],
            "hourly_wage": 20,
            "max_calls_per_shift": 40,
            "min_calls_per_shift": 5,
        },
    ]
    solution = optimize_hourly_staffing(
        np.full(24, 1),
        shift_starts=[0, 8],
        hourly_capacity=2,
        max_calls_per_shift=48,
        daily_budget=500,
        roster=roster,
    )

    assert set(solution.assignments.agent) == {"A1", "A2"}
    assert set(solution.assignments.shift_start) == {"00:00", "08:00"}
    assert solution.total_cost == 400


def test_forecast_and_optimizer_reject_invalid_inputs():
    with pytest.raises(ValueError, match="after the latest observed"):
        forecast_hourly_demand(make_hourly_history(), "2026-03-11", "BRONX")

    with pytest.raises(ValueError, match="24 finite"):
        optimize_hourly_staffing([1, 2, 3])

    with pytest.raises(ValueError, match="missing required columns"):
        parse_agent_roster("data:text/csv;base64,YWdlbnRfaWQKQTEK")
