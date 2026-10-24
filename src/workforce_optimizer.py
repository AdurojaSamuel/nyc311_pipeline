"""Hourly call-demand forecasting and integer staffing optimization."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


@dataclass(frozen=True)
class WorkforceSolution:
    hourly: pd.DataFrame
    assignments: pd.DataFrame
    total_cost: float
    unmet_calls: int
    budget_remaining: float
    solver_status: str


def _daily_matrix(history: pd.DataFrame, borough: str) -> pd.DataFrame:
    selected = history if borough == "ALL" else history[history["borough"] == borough]
    if selected.empty:
        raise ValueError("No recent NYC 311 request data exists for the selected borough.")
    hourly = selected.groupby(["day", "hour"], as_index=False)["requests"].sum()
    dates = pd.date_range(hourly["day"].min(), hourly["day"].max(), freq="D")
    complete = (
        hourly.pivot(index="day", columns="hour", values="requests")
        .reindex(index=dates, columns=range(24), fill_value=0)
        .fillna(0)
    )
    complete.index.name = "day"
    return complete


def forecast_hourly_demand(
    history: pd.DataFrame,
    target_date: str | pd.Timestamp,
    borough: str = "ALL",
    *,
    calls_per_request: float = 0.05,
    backtest_days: int = 28,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Use recent same-weekday hourly request averages and rolling-origin validation."""
    matrix = _daily_matrix(history, borough)
    if not np.isfinite(calls_per_request) or calls_per_request < 0:
        raise ValueError("Calls per service request must be finite and non-negative.")
    target = pd.Timestamp(target_date).normalize()
    if target <= matrix.index.max():
        raise ValueError("Forecast date must be after the latest observed request date.")
    if len(matrix) < 28:
        raise ValueError("At least 28 days of hourly request history are required.")

    def predict(day: pd.Timestamp) -> np.ndarray:
        same_weekday = matrix.loc[
            (matrix.index < day)
            & (matrix.index >= day - pd.Timedelta(days=56))
            & (matrix.index.dayofweek == day.dayofweek)
        ]
        if same_weekday.empty:
            raise ValueError(f"No prior same-weekday data is available for {day.date()}.")
        return same_weekday.mean(axis=0).to_numpy(dtype=float)

    cutoff = max(matrix.index.min() + pd.Timedelta(days=56), matrix.index.max() - pd.Timedelta(days=backtest_days - 1))
    actual_values = []
    predicted_values = []
    for day in matrix.index[matrix.index >= cutoff]:
        prediction = predict(day)
        actual = matrix.loc[day].to_numpy(dtype=float)
        predicted_values.extend(prediction.tolist())
        actual_values.extend(actual.tolist())

    errors = (
        np.asarray(actual_values) - np.asarray(predicted_values)
    ) * calls_per_request
    forecast_requests = np.maximum(np.rint(predict(target)), 0).astype(int)
    forecast_calls = np.maximum(np.rint(forecast_requests * calls_per_request), 0).astype(int)
    result = pd.DataFrame(
        {
            "hour": np.arange(24),
            "forecast_calls": forecast_calls,
            "forecast_requests_proxy": forecast_requests,
        }
    )
    metrics = {
        "validation_mae": float(np.mean(np.abs(errors))),
        "validation_rmse": float(np.sqrt(np.mean(np.square(errors)))),
        "validation_observations": float(len(errors)),
    }
    return result, metrics


def parse_agent_roster(contents: str) -> list[dict[str, object]]:
    """Parse a CSV roster with eligible shifts and per-agent workload/cost inputs."""
    try:
        _, encoded = contents.split(",", 1)
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8-sig")
        frame = pd.read_csv(io.StringIO(decoded))
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as error:
        raise ValueError("Roster upload must be a valid UTF-8 CSV file.") from error
    required = {"agent_id", "eligible_shifts", "hourly_wage", "max_calls_per_shift"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Roster CSV is missing required columns: {', '.join(sorted(missing))}.")
    if frame.empty or frame["agent_id"].isna().any() or frame["agent_id"].astype(str).duplicated().any():
        raise ValueError("Roster CSV needs at least one unique, non-empty agent_id.")
    agents: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        try:
            eligible_shifts = sorted(
                {int(item.strip()) for item in str(row["eligible_shifts"]).split(",") if item.strip()}
            )
            wage = float(row["hourly_wage"])
            maximum = int(row["max_calls_per_shift"])
            minimum = int(row.get("min_calls_per_shift", 0) or 0)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Roster row {row['agent_id']!r} has invalid staffing values.") from error
        if not eligible_shifts or not np.isfinite(wage) or wage < 0 or maximum < 0 or minimum < 0 or minimum > maximum:
            raise ValueError(f"Roster row {row['agent_id']!r} has invalid shift, cost, or workload limits.")
        agents.append(
            {
                "agent_id": str(row["agent_id"]),
                "eligible_shifts": eligible_shifts,
                "hourly_wage": wage,
                "max_calls_per_shift": maximum,
                "min_calls_per_shift": minimum,
            }
        )
    return agents


def optimize_hourly_staffing(
    forecast: pd.DataFrame | list[int] | np.ndarray,
    *,
    available_agents: int = 35,
    shift_starts: tuple[int, ...] | list[int] = (0, 4, 8, 12, 16),
    shift_length: int = 8,
    hourly_capacity: float = 6.0,
    break_hour_offset: int = 4,
    break_capacity_factor: float = 0.5,
    max_calls_per_shift: int = 48,
    min_calls_per_shift: int = 0,
    hourly_wage: float = 25.0,
    daily_budget: float = 5500.0,
    roster: list[dict[str, object]] | None = None,
    time_limit_seconds: float = 30.0,
) -> WorkforceSolution:
    """Minimize hourly unmet demand, then shift cost, with an integer MILP."""
    if isinstance(forecast, pd.DataFrame):
        demand = np.asarray(forecast["forecast_calls"], dtype=float).reshape(-1)
    else:
        demand = np.asarray(forecast, dtype=float).reshape(-1)
    if len(demand) != 24 or not np.isfinite(demand).all() or (demand < 0).any():
        raise ValueError("Forecast must contain 24 finite, non-negative hourly call counts.")
    demand = np.rint(demand).astype(int)
    if (
        available_agents < 1
        or shift_length < 1
        or shift_length > 24
        or hourly_capacity <= 0
        or not 0 <= break_hour_offset < shift_length
        or not 0 < break_capacity_factor <= 1
        or max_calls_per_shift < 0
        or min_calls_per_shift < 0
        or min_calls_per_shift > max_calls_per_shift
        or hourly_wage < 0
        or daily_budget < 0
    ):
        raise ValueError("One or more staffing, capacity, workload, or budget inputs are invalid.")
    starts = sorted(set(int(start) for start in shift_starts))
    if not starts or any(start < 0 or start + shift_length > 24 for start in starts):
        raise ValueError("Shift starts must define at least one shift fully contained in the 24-hour day.")

    if roster:
        agent_configs = {}
        for row in roster:
            agent_id = str(row["agent_id"])
            eligible = sorted({int(start) for start in row["eligible_shifts"]})
            if (
                not eligible
                or any(start not in starts for start in eligible)
                or any(start + shift_length > 24 for start in eligible)
            ):
                raise ValueError(f"Roster agent {agent_id!r} has an invalid or unavailable shift start.")
            wage = float(row["hourly_wage"])
            maximum = int(row["max_calls_per_shift"])
            minimum = int(row.get("min_calls_per_shift", 0))
            if not np.isfinite(wage) or wage < 0 or maximum < 0 or minimum < 0 or minimum > maximum:
                raise ValueError(f"Roster agent {agent_id!r} has invalid cost or workload limits.")
            agent_configs[agent_id] = {
                "eligible_shifts": eligible,
                "hourly_wage": wage,
                "max_calls_per_shift": maximum,
                "min_calls_per_shift": minimum,
            }
    else:
        agent_configs = {
            f"Agent {index + 1:02d}": {
                "eligible_shifts": starts,
                "hourly_wage": float(hourly_wage),
                "max_calls_per_shift": int(max_calls_per_shift),
                "min_calls_per_shift": int(min_calls_per_shift),
            }
            for index in range(available_agents)
        }
    if not agent_configs:
        raise ValueError("At least one available agent must be provided.")
    agents = list(agent_configs)
    shifts_by_agent = {
        agent: list(agent_configs[agent]["eligible_shifts"]) for agent in agents
    }
    shift_options = [(agent, start) for agent in agents for start in shifts_by_agent[agent]]
    y_index = {option: index for index, option in enumerate(shift_options)}
    next_index = len(shift_options)
    x_index = {(agent, hour): next_index + agent_no * 24 + hour for agent_no, agent in enumerate(agents) for hour in range(24)}
    next_index += len(agents) * 24
    u_index = {hour: next_index + hour for hour in range(24)}
    variable_count = next_index + 24
    variable_cost = np.zeros(variable_count, dtype=float)
    for (agent, _), index in y_index.items():
        variable_cost[index] = float(agent_configs[agent]["hourly_wage"]) * shift_length
    unserved_cost = np.zeros(variable_count, dtype=float)
    for index in u_index.values():
        unserved_cost[index] = 1.0
    integrality = np.ones(variable_count, dtype=np.uint8)
    lower_bounds = np.zeros(variable_count, dtype=float)
    upper_bounds = np.full(variable_count, np.inf, dtype=float)
    for index in y_index.values():
        upper_bounds[index] = 1

    row_indices: list[int] = []
    column_indices: list[int] = []
    coefficients: list[float] = []
    row_lowers: list[float] = []
    row_uppers: list[float] = []

    def add_row(terms: dict[int, float], lower: float, upper: float) -> None:
        row = len(row_lowers)
        row_lowers.append(lower)
        row_uppers.append(upper)
        for column, value in terms.items():
            if value:
                row_indices.append(row)
                column_indices.append(column)
                coefficients.append(value)

    for hour in range(24):
        terms = {x_index[agent, hour]: 1.0 for agent in agents}
        terms[u_index[hour]] = 1.0
        add_row(terms, float(demand[hour]), float(demand[hour]))

    for agent in agents:
        agent_starts = shifts_by_agent[agent]
        agent_y = [y_index[agent, start] for start in agent_starts]
        add_row({index: 1.0 for index in agent_y}, 0.0, 1.0)
        workload_terms = {x_index[agent, hour]: 1.0 for hour in range(24)}
        for index in agent_y:
            workload_terms[index] = -float(agent_configs[agent]["max_calls_per_shift"])
        add_row(workload_terms, -np.inf, 0.0)
        minimum_terms = {x_index[agent, hour]: -1.0 for hour in range(24)}
        for index in agent_y:
            minimum_terms[index] = float(agent_configs[agent]["min_calls_per_shift"])
        add_row(minimum_terms, -np.inf, 0.0)
        for hour in range(24):
            terms = {x_index[agent, hour]: 1.0}
            for start in agent_starts:
                if start <= hour < start + shift_length:
                    capacity_fraction = (
                        break_capacity_factor
                        if hour == start + break_hour_offset
                        else 1.0
                    )
                    terms[y_index[agent, start]] = -hourly_capacity * capacity_fraction
            add_row(terms, -np.inf, 0.0)

    add_row(
        {
            index: float(agent_configs[agent]["hourly_wage"]) * shift_length
            for (agent, _), index in y_index.items()
        },
        -np.inf,
        float(daily_budget),
    )
    matrix = coo_matrix(
        (coefficients, (row_indices, column_indices)),
        shape=(len(row_lowers), variable_count),
    ).tocsr()
    constraints = LinearConstraint(matrix, np.asarray(row_lowers), np.asarray(row_uppers))
    bounds = Bounds(lower_bounds, upper_bounds)
    solver_options = {"time_limit": float(time_limit_seconds), "mip_rel_gap": 0.01}

    service_result = milp(
        unserved_cost,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
        options=solver_options,
    )
    if service_result.x is None:
        raise RuntimeError(f"Service-coverage MILP did not find a feasible result: {service_result.message}")
    best_unserved = int(round(float(np.sum(service_result.x[list(u_index.values())]))))

    service_floor = np.zeros(variable_count, dtype=float)
    for index in u_index.values():
        service_floor[index] = 1.0
    lexicographic = LinearConstraint(
        coo_matrix(service_floor.reshape(1, -1)).tocsr(),
        -np.inf,
        float(best_unserved),
    )
    cost_result = milp(
        variable_cost,
        integrality=integrality,
        bounds=bounds,
        constraints=(constraints, lexicographic),
        options=solver_options,
    )
    selected_result = cost_result if cost_result.x is not None else service_result
    solution = selected_result.x
    if solution is None:
        raise RuntimeError(f"Staffing MILP did not return a solution: {selected_result.message}")

    hourly_rows = []
    for hour in range(24):
        staffed = 0
        effective_capacity = 0.0
        for agent in agents:
            for start in shifts_by_agent[agent]:
                if start <= hour < start + shift_length and solution[y_index[agent, start]] > 0.5:
                    staffed += 1
                    effective_capacity += hourly_capacity * (
                        break_capacity_factor
                        if hour == start + break_hour_offset
                        else 1.0
                    )
        handled = int(round(sum(solution[x_index[agent, hour]] for agent in agents)))
        unmet = int(round(solution[u_index[hour]]))
        hourly_rows.append(
            {
                "hour": hour,
                "forecast_calls": int(demand[hour]),
                "staffed_agents": staffed,
                "handling_capacity": effective_capacity,
                "calls_served": handled,
                "unmet_calls": unmet,
            }
        )
    hourly = pd.DataFrame(hourly_rows)

    assignments = []
    for agent, start in shift_options:
        if solution[y_index[agent, start]] > 0.5:
            workload = int(round(sum(solution[x_index[agent, hour]] for hour in range(start, start + shift_length))))
            assignments.append(
                {
                    "agent": agent,
                    "shift_start": f"{start:02d}:00",
                    "shift_end": f"{(start + shift_length) % 24:02d}:00",
                    "calls_assigned": workload,
                    "shift_cost": float(agent_configs[agent]["hourly_wage"]) * shift_length,
                }
            )
    assignment_frame = pd.DataFrame(
        assignments,
        columns=["agent", "shift_start", "shift_end", "calls_assigned", "shift_cost"],
    )
    total_cost = float(assignment_frame["shift_cost"].sum())
    unmet_calls = int(hourly["unmet_calls"].sum())
    return WorkforceSolution(
        hourly=hourly,
        assignments=assignment_frame,
        total_cost=total_cost,
        unmet_calls=unmet_calls,
        budget_remaining=float(daily_budget - total_cost),
        solver_status=str(selected_result.message),
    )
