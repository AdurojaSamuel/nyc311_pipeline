import numpy as np
import pytest
from mlflow.tracking import MlflowClient

from forecasting import MODEL_NAMES, train_forecast


def test_best_forecast_trains_candidates_and_logs_best_run(monkeypatch, tmp_path):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'runs.db'}")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "forecast-tests")
    monkeypatch.setenv("MLFLOW_ARTIFACT_URI", (tmp_path / "artifacts").as_uri())
    rng = np.random.default_rng(311)
    history = 500 + np.arange(60) * 2 + 40 * np.sin(np.arange(60) * 2 * np.pi / 12)
    history = history + rng.normal(0, 4, len(history))

    result = train_forecast(history, 4, "Best")

    assert result.model in MODEL_NAMES
    assert result.forecast.shape == (4,)
    assert np.isfinite(result.forecast).all()
    assert result.validation_mae == result.candidate_scores[result.model]
    assert set(result.candidate_scores) == set(MODEL_NAMES)
    assert result.best_run_id
    client = MlflowClient()
    experiment = client.get_experiment_by_name("forecast-tests")
    assert experiment.artifact_location == (tmp_path / "artifacts").as_uri()
    best_run = client.get_run(result.best_run_id)
    assert best_run.data.tags["selection_status"] == "best"
    assert best_run.data.metrics["validation_mae"] == result.validation_mae


def test_forecast_rejects_short_history():
    with pytest.raises(ValueError, match="24 monthly observations"):
        train_forecast(np.arange(12, dtype=float), 3)
