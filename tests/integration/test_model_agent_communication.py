"""Integration tests covering agent ↔ model communication pipeline."""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.model_discovery import ModelDiscovery


class _FakeModel(MCPModelNode):
    """Lightweight fake model node for integration tests."""

    def __init__(
        self,
        name: str,
        prediction: float = 0.0,
        confidence: float = 0.5,
        health_status: str = "healthy",
    ):
        self._name = name
        self._prediction_value = prediction
        self._confidence = confidence
        self._health_status = health_status
        self._model_version = "1.0.0"
        self._model_type = "fake"

    async def initialize(self):
        return None

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        return MCPModelPrediction(
            model_name=self.model_name,
            model_version=self.model_version,
            prediction=self._prediction_value,
            confidence=self._confidence,
            reasoning="Fake model prediction",
            features_used=[f"feature_{idx}" for idx, _ in enumerate(request.features)],
            feature_importance={
                f"feature_{idx}": 1 / len(request.features) if request.features else 0.0
                for idx, _ in enumerate(request.features)
            },
            computation_time_ms=1.0,
            health_status=self._health_status,
        )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "health_status": self._health_status,
        }

    async def get_health_status(self) -> Dict[str, Any]:
        return {"status": self._health_status, "model_loaded": True}

    @property
    def model_name(self) -> str:
        return self._name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return self._model_type


@pytest_asyncio.fixture
async def registry():
    """Initialized model registry for tests."""
    reg = MCPModelRegistry()
    await reg.initialize()
    yield reg
    await reg.shutdown()


@pytest.mark.asyncio
async def test_model_discovery_across_directories(tmp_path: Path, registry):
    """Ensure discovery scans known subdirectories and registers models."""
    model_dir = tmp_path
    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True

        discovery = ModelDiscovery(registry)
        discovery.model_dir = model_dir
        discovery.model_path = None
    subdirs = [
        "xgboost",
        "lightgbm",
        "random_forest",
        "lstm",
        "transformer",
        "custom",
    ]
    expected_model_names = []
    for subdir in subdirs:
        subdir_path = model_dir / subdir
        subdir_path.mkdir(parents=True, exist_ok=True)
        model_path = subdir_path / f"{subdir}_model.pkl"
        model_path.write_bytes(b"fake model content")
        expected_model_names.append(model_path.stem)

        async def _fake_loader(path: Path) -> MCPModelNode:
            return _FakeModel(path.stem)

        with patch.object(ModelDiscovery, "_load_model_from_path", side_effect=_fake_loader):
            discovered = await discovery.discover_models()

        assert len(discovered) == len(expected_model_names)
        for model_name in expected_model_names:
            assert model_name in discovered
            assert registry.get_model(model_name) is not None


@pytest.mark.asyncio
async def test_model_registry_prediction_flow(registry):
    """Verify registry fan-out, aggregation, and consensus calculation."""
    bullish = _FakeModel("bull_model", prediction=0.9, confidence=0.8)
    bearish = _FakeModel("bear_model", prediction=-0.4, confidence=0.4)
    degraded = _FakeModel("bad_model", prediction=0.0, confidence=0.0, health_status="degraded")

    registry.register_model(bullish)
    registry.register_model(bearish)
    registry.register_model(degraded)

    request = MCPModelRequest(
        request_id="req-123",
        features=[1.0, 2.0, 3.0],
        context={"feature_names": ["a", "b", "c"]},
        require_explanation=True,
    )

    response = await registry.get_predictions(request)

    assert response.total_models == 3
    assert response.healthy_models == 2  # degraded model excluded from consensus
    assert len(response.predictions) == 3
    assert response.consensus_confidence > 0
    assert -1.0 <= response.consensus_prediction <= 1.0


@pytest.mark.asyncio
async def test_model_registry_handles_prediction_errors(registry):
    """Ensure registry degrades a model that raises during prediction."""

    class _FailingModel(_FakeModel):
        async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
            raise RuntimeError("boom")

    good = _FakeModel("good_model", prediction=0.6, confidence=0.9)
    bad = _FailingModel("bad_model")
    registry.register_model(good)
    registry.register_model(bad)

    request = MCPModelRequest(
        request_id="req-456",
        features=[0.1, 0.2],
        context={},
        require_explanation=False,
    )

    response = await registry.get_predictions(request)

    assert len(response.predictions) == 2
    degraded = next(pred for pred in response.predictions if pred.model_name == "bad_model")
    assert degraded.health_status == "degraded"
    assert degraded.confidence == 0.0


@pytest.mark.asyncio
async def test_model_registry_health_status(registry):
    """Health report aggregates registry tracking metrics."""
    healthy = _FakeModel("healthy_model", prediction=0.1, confidence=0.6)
    unhealthy = _FakeModel("unhealthy_model", prediction=0.0, confidence=0.1, health_status="unhealthy")
    registry.register_model(healthy)
    registry.register_model(unhealthy)

    request = MCPModelRequest(
        request_id="req-789",
        features=[1.0],
        context={},
        require_explanation=False,
    )
    await registry.get_predictions(request)

    health = await registry.get_health_status()
    assert health["total_models"] == 2
    assert health["healthy_models"] == 1
    assert "healthy_model" in health["model_statuses"]
    assert "unhealthy_model" in health["model_statuses"]

