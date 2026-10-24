"""Call-center staffing optimization using Erlang-C service-level constraints."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def erlang_c_service_level(
    calls_per_hour: float,
    handle_time_minutes: float,
    agents: int,
    answer_seconds: float,
) -> float:
    """Return the Erlang-C probability of answering within the target time."""
    if calls_per_hour < 0 or handle_time_minutes <= 0 or answer_seconds < 0:
        raise ValueError("Call volume and answer time must be non-negative; handle time must be positive.")
    if calls_per_hour == 0:
        return 1.0
    offered_load = calls_per_hour * handle_time_minutes / 60
    if agents <= offered_load or agents < 1:
        return 0.0

    log_terms = np.arange(agents, dtype=float) * math.log(offered_load) - np.array(
        [math.lgamma(index + 1) for index in range(agents)]
    ) if offered_load > 0 else np.array([0.0] + [-math.inf] * (agents - 1))
    log_wait_term = (
        agents * math.log(offered_load)
        - math.lgamma(agents + 1)
        + math.log(agents / (agents - offered_load))
        if offered_load > 0
        else -math.inf
    )
    max_log = max(float(np.max(log_terms)), log_wait_term)
    log_denominator = max_log + math.log(
        float(np.exp(log_terms - max_log).sum()) + math.exp(log_wait_term - max_log)
    )
    wait_probability = math.exp(log_wait_term - log_denominator)
    return min(
        1.0,
        max(0.0, 1 - wait_probability * math.exp(-(agents - offered_load) * answer_seconds / (handle_time_minutes * 60))),
    )


def optimize_staffing(
    monthly_forecast: pd.Series | np.ndarray,
    *,
    calls_per_request: float = 1.0,
    handle_time_minutes: float = 8.0,
    operating_hours_per_day: float = 8.0,
    business_days_per_month: int = 22,
    hourly_wage: float = 25.0,
    shrinkage: float = 0.30,
    occupancy_limit: float = 0.85,
    service_level_target: float = 0.80,
    answer_seconds: float = 20.0,
) -> pd.DataFrame:
    """Find the lowest-cost monthly staffing level satisfying service constraints."""
    assumptions = (
        calls_per_request >= 0
        and handle_time_minutes > 0
        and operating_hours_per_day > 0
        and business_days_per_month > 0
        and hourly_wage >= 0
        and 0 <= shrinkage < 1
        and 0 < occupancy_limit <= 1
        and 0 < service_level_target < 1
        and answer_seconds >= 0
    )
    if not assumptions:
        raise ValueError("One or more workforce planning assumptions are outside valid ranges.")

    volumes = np.asarray(monthly_forecast, dtype=float).reshape(-1)
    if not len(volumes) or not np.isfinite(volumes).all() or (volumes < 0).any():
        raise ValueError("Monthly forecast must contain finite, non-negative volumes.")

    rows = []
    for index, volume in enumerate(volumes, start=1):
        calls_per_hour = volume * calls_per_request / (business_days_per_month * operating_hours_per_day)
        offered_load = calls_per_hour * handle_time_minutes / 60
        agents = max(1, math.ceil(offered_load / (occupancy_limit * (1 - shrinkage))))
        while agents < 10000:
            available_agents = agents * (1 - shrinkage)
            occupancy = offered_load / available_agents if available_agents else 1.0
            service_level = erlang_c_service_level(
                calls_per_hour,
                handle_time_minutes,
                max(1, math.floor(available_agents)),
                answer_seconds,
            )
            if occupancy <= occupancy_limit and service_level >= service_level_target:
                break
            agents += 1
        if agents == 10000:
            raise RuntimeError("Could not find a feasible staffing level below 10,000 call takers.")
        rows.append(
            {
                "month_number": index,
                "forecast_calls": float(volume * calls_per_request),
                "calls_per_hour": calls_per_hour,
                "call_takers": agents,
                "occupancy": occupancy,
                "service_level": service_level,
                "monthly_labor_cost": agents * operating_hours_per_day * business_days_per_month * hourly_wage,
            }
        )

    result = pd.DataFrame(rows)
    fixed_staff = int(result["call_takers"].max())
    fixed_monthly_cost = fixed_staff * operating_hours_per_day * business_days_per_month * hourly_wage
    result["fixed_staff_baseline"] = fixed_staff
    result["fixed_monthly_cost"] = fixed_monthly_cost
    result["monthly_savings"] = fixed_monthly_cost - result["monthly_labor_cost"]
    return result
