"""Unit tests for transformer-aware MCP orchestrator dry-run validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.mcp_orchestrator import MCPOrchestrator, _build_transformer_dry_run_context
from agent.models.mcp_model_node import MCPModelPrediction
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelResponse
from feature_store.transformer_btcusd.contract import SUPPORTED_RESOLUTIONS


def test_build_transformer_dry_run_context_keys() -> None:
    ctx = _build_transformer_dry_run_context("BTCUSD")
    assert ctx["symbol"] == "BTCUSD"
    assert ctx["dry_run"] is True
    for res in SUPPORTED_RESOLUTIONS:
        key = f"v43_df{res}"
        assert key in ctx
        assert len(ctx[key]) >= 128


@pytest.mark.asyncio
async def test_validate_models_dry_run_transformer_context() -> None:
    orchestrator = MCPOrchestrator()
    registry = MCPModelRegistry()
    model = MagicMock()
    model.model_name = "jacksparrow_transformer_BTCUSD_15m"
    model.model_type = "transformer"
    registry.register_model(model)
    orchestrator.model_registry = registry
    orchestrator._required_feature_names_cache = ["ret_1", "rsi_14"]

    prediction = MCPModelPrediction(
        model_name="jacksparrow_transformer_BTCUSD_15m",
        model_version="v1",
        prediction=0.5,
        confidence=0.7,
        reasoning="dry run",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status="healthy",
        context={"path_edge": 0.01},
    )
    registry.get_predictions = AsyncMock(
        return_value=MCPModelResponse(
            request_id="dry_run_validation",
            predictions=[prediction],
            consensus_prediction=0.5,
            consensus_confidence=0.7,
            healthy_models=1,
            total_models=1,
            timestamp=MagicMock(),
        )
    )

    result = await orchestrator.validate_models_dry_run()
    assert result is True

    req = registry.get_predictions.await_args.args[0]
    assert "v43_df5m" in req.context
    assert "v43_df15m" in req.context
    assert req.features == []
