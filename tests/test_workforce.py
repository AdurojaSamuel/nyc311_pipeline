import math

import pandas as pd
import pytest

from workforce import erlang_c_service_level, optimize_staffing


def test_erlang_c_matches_known_service_level():
    # With one Erlang of load and two agents, the wait probability is 1/3.
    expected = 1 - (1 / 3) * math.exp(-20 / 360)
    assert erlang_c_service_level(10, 6, 2, 20) == pytest.approx(expected, rel=1e-8)


def test_staffing_meets_constraints_and_compares_peak_baseline():
    result = optimize_staffing(
        pd.Series([9000.0, 15000.0, 7000.0]),
        calls_per_request=1.0,
        handle_time_minutes=8.0,
        hourly_wage=25.0,
    )

    assert (result["service_level"] >= 0.80).all()
    assert (result["occupancy"] <= 0.85).all()
    assert result["fixed_staff_baseline"].nunique() == 1
    assert (result["monthly_savings"] >= 0).all()
    assert result.loc[1, "monthly_labor_cost"] == result.loc[1, "fixed_monthly_cost"]


def test_zero_forecast_needs_no_agents_beyond_roster_minimum():
    result = optimize_staffing([0])
    assert result.loc[0, "call_takers"] == 1
    assert result.loc[0, "service_level"] == 1


def test_invalid_staffing_inputs_are_rejected():
    with pytest.raises(ValueError, match="assumptions"):
        optimize_staffing([100], shrinkage=1.0)

    with pytest.raises(ValueError, match="assumptions"):
        optimize_staffing([100], service_level_target=1.0)
