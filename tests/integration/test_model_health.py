"""Integration tests for model health reporting."""

import os
from typing import Any, Dict

import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction
from agent.models.mcp_model_registry import MCPModelRegistry


class _HealthFakeModel(MCPModelNode):
    def __init__(self, name: str, health_status: str = "healthy"):
        self._name = name
        self._health_status = health_status
        self._model_version = "1.0.0"

    async def initialize(self):
        return None

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        return MCPModelPrediction(
            model_name=self.model_name,
            model_version=self.model_version,
            prediction=0.0,
            confidence=0.0,
            reasoning="",
            features_used=[],
            feature_importance={},
            computation_time_ms=0.1,
            health_status=self._health_status,
        )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": "fake",
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
        return "fake"


@pytest_asyncio.fixture
async def registry():
    reg = MCPModelRegistry()
    await reg.initialize()
    yield reg
    await reg.shutdown()


@pytest.mark.asyncio
async def test_model_health_summary_counts(registry):
    healthy_model = _HealthFakeModel("healthy_model", "healthy")
    degraded_model = _HealthFakeModel("degraded_model", "degraded")
    registry.register_model(healthy_model)
    registry.register_model(degraded_model)

    # Trigger prediction logging for latency/error stats
    request = MCPModelRequest(
        request_id="health-1",
        features=[0.0],
        context={},
        require_explanation=False,
    )
    await registry.get_predictions(request)

    health = await registry.get_health_status()
    assert health["total_models"] == 2
    assert health["healthy_models"] == 1
    assert health["unhealthy_models"] == 1
    assert health["model_statuses"]["healthy_model"]["status"] == "healthy"
    assert health["model_statuses"]["degraded_model"]["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_model_health_handles_exceptions(registry):
    class _BrokenModel(_HealthFakeModel):
        async def get_health_status(self) -> Dict[str, Any]:
            raise RuntimeError("boom")

    healthy_model = _HealthFakeModel("healthy_model", "healthy")
    broken_model = _BrokenModel("broken_model", "healthy")
    registry.register_model(healthy_model)
    registry.register_model(broken_model)

    health = await registry.get_health_status()
    assert health["model_statuses"]["broken_model"]["status"] == "unknown"
    assert "error" in health["model_statuses"]["broken_model"]

