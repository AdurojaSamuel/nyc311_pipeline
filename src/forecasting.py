"""Monthly call-volume forecasting with holdout-based model selection."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
MODEL_NAMES = ("Holt-Winters", "AutoARIMA", "LSTM")


@dataclass(frozen=True)
class ForecastResult:
    model: str
    forecast: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    validation_mae: float
    candidate_scores: dict[str, float]
    best_run_id: str


def _fit_forecast(model_name: str, values: np.ndarray, horizon: int) -> np.ndarray:
    if len(values) < 18:
        raise ValueError("At least 18 monthly observations are required to fit these models.")

    if model_name == "Holt-Winters":
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        seasonal_periods = 12 if len(values) >= 24 else None
        fitted = ExponentialSmoothing(
            values,
            trend="add",
            seasonal="add" if seasonal_periods else None,
            seasonal_periods=seasonal_periods,
            initialization_method="estimated",
        ).fit(optimized=True)
        prediction = fitted.forecast(horizon)
    elif model_name == "AutoARIMA":
        from pmdarima import auto_arima
        from threadpoolctl import threadpool_limits

        with threadpool_limits(limits=1):
            fitted = auto_arima(
                values,
                seasonal=len(values) >= 24,
                m=12 if len(values) >= 24 else 1,
                stepwise=True,
                suppress_warnings=False,
                error_action="raise",
                max_p=2,
                max_q=2,
                max_P=1,
                max_Q=1,
                max_order=4,
                maxiter=50,
            )
        prediction = fitted.predict(n_periods=horizon)
    elif model_name == "LSTM":
        import torch
        from torch import nn

        torch.manual_seed(311)
        torch.set_num_threads(1)
        scale = float(np.std(values))
        scale = scale if np.isfinite(scale) and scale > 0 else 1.0
        center = float(np.mean(values))
        normalized = (values - center) / scale
        window = min(12, max(3, len(values) // 4))
        features = []
        targets = []
        for index in range(window, len(normalized)):
            features.append(normalized[index - window : index])
            targets.append(normalized[index])
        inputs = torch.tensor(np.asarray(features), dtype=torch.float32).unsqueeze(-1)
        labels = torch.tensor(np.asarray(targets), dtype=torch.float32).unsqueeze(-1)

        class VolumeLSTM(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.lstm = nn.LSTM(input_size=1, hidden_size=16, batch_first=True)
                self.output = nn.Linear(16, 1)

            def forward(self, sequence):
                encoded, _ = self.lstm(sequence)
                return self.output(encoded[:, -1, :])

        network = VolumeLSTM()
        optimizer = torch.optim.Adam(network.parameters(), lr=0.01)
        loss_function = nn.MSELoss()
        for _ in range(60):
            optimizer.zero_grad()
            loss = loss_function(network(inputs), labels)
            loss.backward()
            optimizer.step()

        sequence = normalized[-window:].tolist()
        forecast = []
        network.eval()
        with torch.no_grad():
            for _ in range(horizon):
                sample = torch.tensor(sequence[-window:], dtype=torch.float32).view(1, window, 1)
                next_value = float(network(sample).item())
                forecast.append(next_value * scale + center)
                sequence.append(next_value)
        prediction = forecast
    else:
        raise ValueError(f"Unsupported forecasting model: {model_name}")

    result = np.asarray(prediction, dtype=float).reshape(-1)
    if len(result) != horizon or not np.isfinite(result).all():
        raise RuntimeError(f"{model_name} returned an invalid forecast.")
    return np.maximum(result, 0)


def _tracking_setup():
    import mlflow

    default_store = (Path.home() / ".nyc311_pipeline" / "mlflow.db").resolve()
    default_store.parent.mkdir(parents=True, exist_ok=True)
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{default_store}")
    mlflow.set_tracking_uri(tracking_uri)
    experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "nyc311-call-volume")
    client = mlflow.tracking.MlflowClient()
    if client.get_experiment_by_name(experiment_name) is None:
        if tracking_uri.startswith("sqlite:"):
            default_artifacts = default_store.parent / "artifacts"
            default_artifacts.mkdir(parents=True, exist_ok=True)
            artifact_uri = os.getenv("MLFLOW_ARTIFACT_URI", default_artifacts.resolve().as_uri())
            client.create_experiment(experiment_name, artifact_location=artifact_uri)
        else:
            client.create_experiment(experiment_name)
    mlflow.set_experiment(experiment_name)
    return mlflow


def train_forecast(
    history: pd.Series | np.ndarray,
    horizon: int,
    model: str = "Best",
) -> ForecastResult:
    """Compare candidates on a chronological holdout, fit the chosen model, and log runs."""
    values = np.asarray(history, dtype=float).reshape(-1)
    values = values[np.isfinite(values)]
    if horizon < 1:
        raise ValueError("Forecast horizon must be at least one month.")
    if len(values) < 24:
        raise ValueError("At least 24 monthly observations are required for model selection.")
    if model not in (*MODEL_NAMES, "Best"):
        raise ValueError(f"Unknown model {model!r}; choose one of {(*MODEL_NAMES, 'Best')}.")

    mlflow = _tracking_setup()
    holdout_size = min(12, max(3, len(values) // 5))
    training_values = values[:-holdout_size]
    holdout = values[-holdout_size:]
    candidates = MODEL_NAMES if model == "Best" else (model,)
    candidate_runs: dict[str, str] = {}
    candidate_scores: dict[str, float] = {}
    candidate_errors: dict[str, str] = {}

    for candidate in candidates:
        try:
            validation_forecast = _fit_forecast(candidate, training_values, holdout_size)
            mae = float(np.mean(np.abs(holdout - validation_forecast)))
            with mlflow.start_run(run_name=f"{candidate}-holdout") as run:
                mlflow.log_param("model", candidate)
                mlflow.log_param("training_observations", len(training_values))
                mlflow.log_param("holdout_observations", holdout_size)
                mlflow.log_metric("validation_mae", mae)
                mlflow.log_metric("validation_rmse", float(np.sqrt(np.mean((holdout - validation_forecast) ** 2))))
                mlflow.set_tag("selection_status", "candidate")
                candidate_runs[candidate] = run.info.run_id
            candidate_scores[candidate] = mae
        except Exception as error:
            candidate_errors[candidate] = str(error)
            LOGGER.exception("Model candidate %s failed during holdout evaluation.", candidate)
            with mlflow.start_run(run_name=f"{candidate}-failed") as run:
                mlflow.log_param("model", candidate)
                mlflow.log_param("failure", str(error)[:500])
                mlflow.set_tag("selection_status", "failed")

    if not candidate_scores:
        details = "; ".join(f"{name}: {message}" for name, message in candidate_errors.items())
        raise RuntimeError(f"All forecasting models failed: {details}")

    selected = min(candidate_scores, key=candidate_scores.get) if model == "Best" else model
    forecast = _fit_forecast(selected, values, horizon)
    residual_scale = max(candidate_scores[selected] * 1.96, float(np.std(values[-12:]) * 0.1), 1.0)
    widening = residual_scale * np.sqrt(np.arange(1, horizon + 1))
    lower = np.maximum(forecast - widening, 0)
    upper = forecast + widening

    with mlflow.start_run(run_name=f"{selected}-best-fit") as run:
        mlflow.log_param("model", selected)
        mlflow.log_param("selection_requested", model)
        mlflow.log_param("training_observations", len(values))
        mlflow.log_param("forecast_horizon", horizon)
        mlflow.log_metric("validation_mae", candidate_scores[selected])
        mlflow.log_metrics({f"{name}_validation_mae": score for name, score in candidate_scores.items()})
        mlflow.set_tag("selection_status", "best" if model == "Best" else "manual")
        mlflow.log_dict(
            {
                "model": selected,
                "validation_mae": candidate_scores[selected],
                "candidate_scores": candidate_scores,
                "failed_candidates": candidate_errors,
                "forecast": forecast.tolist(),
            },
            "forecast_result.json",
        )
        best_run_id = run.info.run_id

    if selected in candidate_runs and model == "Best":
        mlflow.tracking.MlflowClient().set_tag(candidate_runs[selected], "selection_status", "best_candidate")

    return ForecastResult(
        selected,
        forecast,
        lower,
        upper,
        candidate_scores[selected],
        candidate_scores,
        best_run_id,
    )


def forecast_for_apps(history, horizon: int, model: str = "Best") -> dict:
    """Return JSON-friendly forecast fields for the Python and R dashboards."""
    result = train_forecast(history, horizon, model)
    return {
        "model": result.model,
        "forecast": result.forecast.tolist(),
        "lower": result.lower.tolist(),
        "upper": result.upper.tolist(),
        "validation_mae": result.validation_mae,
        "candidate_scores": result.candidate_scores,
        "best_run_id": result.best_run_id,
    }
