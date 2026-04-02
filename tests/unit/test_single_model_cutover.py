import os
from datetime import datetime
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

from agent.core.config import settings
from agent.core.learning_system import LearningSystem
from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest, ReasoningStep
from agent.learning.retraining_scheduler import RetrainingScheduler
from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry


class _DummyClassifier:
    def predict_proba(self, X):  # noqa: N803
        return [[0.2, 0.2, 0.6] for _ in range(len(X))]


@pytest.mark.asyncio
async def test_runtime_confidence_calibration_uses_learned_factors():
    learning = LearningSystem()
    await learning.initialize()
    learning.confidence_calibration.calibration_factors = {"single_model": 1.4}
    calibrated = await learning.calibrate_runtime_confidence(
        raw_confidence=0.5,
        model_predictions=[{"model_name": "single_model", "confidence": 0.9}],
    )
    assert calibrated == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_reasoning_step5_skips_mtf_when_single_model_enabled(monkeypatch):
    req = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context={
            "model_predictions": [
                {
                    "model_name": "single_model",
                    "prediction": 0.8,
                    "confidence": 0.75,
                    "model_type": "classifier",
                    "context": {"entry_proba": {"sell": 0.1, "hold": 0.2, "buy": 0.7}},
                }
            ],
            "features": {"volatility": 2.0},
            "timestamp": datetime.utcnow(),
        },
    )
    engine = MCPReasoningEngine(feature_server=None, model_registry=None, vector_store=None)
    previous_steps = [
        ReasoningStep(
            step_number=1,
            step_name="stub",
            description="stub",
            evidence=[],
            confidence=0.5,
            timestamp=datetime.utcnow(),
        )
    ]

    monkeypatch.setattr(settings, "single_model_mode_enabled", True, raising=False)
    step = await engine._step5_decision_synthesis(req, previous_steps)
    assert step.description in {
        "STRONG_BUY - High confidence bullish signal",
        "BUY - Moderate bullish signal",
    }


@pytest.mark.asyncio
async def test_model_discovery_single_mode_loads_consolidated(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        metadata = root / "metadata_BTCUSD_consolidated_test.json"
        model_file = root / "consolidated_model_BTCUSD.joblib"
        scaler_file = root / "consolidated_scaler_BTCUSD.joblib"

        import joblib  # type: ignore

        joblib.dump(_DummyClassifier(), model_file)
        joblib.dump(None, scaler_file)
        metadata.write_text(
            """
{
  "model_name": "jacksparrow_BTCUSD_consolidated",
  "version": "1.0.0",
  "features": ["f1", "f2"],
  "artifacts": {
    "model": "consolidated_model_BTCUSD.joblib",
    "scaler": "consolidated_scaler_BTCUSD.joblib"
  }
}
            """.strip(),
            encoding="utf-8",
        )

        registry = MCPModelRegistry()
        discovery = ModelDiscovery(registry)
        discovery.model_dir = root

        monkeypatch.setattr(settings, "single_model_mode_enabled", True, raising=False)
        monkeypatch.setattr(
            settings,
            "consolidated_model_metadata_glob",
            "metadata_BTCUSD_consolidated*.json",
            raising=False,
        )
        monkeypatch.setattr(settings, "model_discovery_recursive", True, raising=False)
        monkeypatch.setattr(settings, "model_auto_register", True, raising=False)

        discovered = await discovery.discover_models()
        assert discovered == ["jacksparrow_BTCUSD_consolidated"]
        assert registry.get_model("jacksparrow_BTCUSD_consolidated") is not None


@pytest.mark.asyncio
async def test_retraining_scheduler_reports_missing_consolidated_artifact(monkeypatch):
    scheduler = RetrainingScheduler()
    monkeypatch.setattr(settings, "retraining_scheduler_enabled", True, raising=False)
    monkeypatch.setattr(settings, "retraining_command", "echo ok", raising=False)
    monkeypatch.setattr(settings, "single_model_mode_enabled", True, raising=False)
    monkeypatch.setattr(
        settings, "consolidated_model_metadata_glob", "metadata_BTCUSD_consolidated*.json", raising=False
    )
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(settings, "model_dir", tmp, raising=False)
        with patch("agent.learning.retraining_scheduler.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = "ok"
            run_mock.return_value.stderr = ""
            result = await scheduler.run(None)
            assert result["success"] is True
            assert result["consolidated_artifact_found"] is False
