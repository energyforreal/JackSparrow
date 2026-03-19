"""Regression tests for model prediction context propagation."""

import os
import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Ensure project root is on path (for agent imports).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force-load local `agent` package in case another installed package shadows it.
agent_init = ROOT / "agent" / "__init__.py"
agent_spec = importlib.util.spec_from_file_location("agent", agent_init)
if agent_spec and agent_spec.loader:
    agent_module = importlib.util.module_from_spec(agent_spec)
    agent_module.__path__ = [str(ROOT / "agent")]
    sys.modules["agent"] = agent_module
    agent_spec.loader.exec_module(agent_module)

# Ensure settings can initialize in test environments.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

from agent.core.mcp_orchestrator import MCPOrchestrator
from agent.models.mcp_model_node import MCPModelPrediction


@pytest.mark.asyncio
async def test_process_prediction_request_preserves_model_context():
    """Per-model context (including exit_signal) is preserved in orchestrator output."""
    orchestrator = MCPOrchestrator()
    orchestrator._initialized = True

    feature_response = SimpleNamespace(
        features=[
            SimpleNamespace(
                name="ema_9",
                value=1.23,
                quality=SimpleNamespace(value="high"),
            )
        ],
        overall_quality=SimpleNamespace(value="high"),
        quality_score=0.97,
    )
    orchestrator.feature_server = SimpleNamespace(
        get_features=AsyncMock(return_value=feature_response)
    )

    prediction = MCPModelPrediction(
        model_name="jacksparrow_BTCUSD_15m",
        model_version="4.0.0",
        prediction=0.4,
        confidence=0.8,
        reasoning="v4 ensemble 15m",
        features_used=["ema_9"],
        feature_importance={},
        computation_time_ms=12.5,
        health_status="healthy",
        context={"entry_signal": 0.4, "exit_signal": -0.6},
    )
    model_response = SimpleNamespace(
        predictions=[prediction],
        consensus_prediction=0.4,
        consensus_confidence=0.8,
        healthy_models=1,
        total_models=1,
    )
    orchestrator.model_registry = SimpleNamespace(
        get_required_feature_names=lambda: ["ema_9"],
        get_predictions=AsyncMock(return_value=model_response),
        models={"jacksparrow_BTCUSD_15m": object()},
    )

    reasoning_chain = SimpleNamespace(
        chain_id="chain-1",
        steps=[],
        conclusion="buy",
        final_confidence=0.81,
    )
    orchestrator.reasoning_engine = SimpleNamespace(
        generate_reasoning=AsyncMock(return_value=reasoning_chain)
    )

    result = await orchestrator.process_prediction_request("BTCUSD", {})

    top_level_ctx = result["model_predictions"][0]["context"]
    market_ctx = result["market_context"]["model_predictions"][0]["context"]
    model_ctx = result["models"]["predictions"][0]["context"]

    assert top_level_ctx["entry_signal"] == 0.4
    assert top_level_ctx["exit_signal"] == -0.6
    assert market_ctx == top_level_ctx
    assert model_ctx == top_level_ctx
