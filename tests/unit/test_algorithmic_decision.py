"""Algorithmic decision path, empty model registry, and the order gate."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.agent_order_registry import AGENT_DECISION_AUTHORITY
from agent.events.schemas import PolicyVerdict
from research.swinging.contract import ALGO_DECISION_PATH


def _verdict_result() -> dict:
    verdict = PolicyVerdict(
        signal="BUY",
        confidence=0.72,
        position_size=0.05,
        reason_codes=["algorithmic_qualified"],
        adopted_ml_candidate=False,
    )
    return {
        "symbol": "BTCUSD",
        "timestamp": datetime.now(timezone.utc),
        "error": None,
        "model_predictions": [],
        "market_context": {
            "decision_path": ALGO_DECISION_PATH,
            "closed_bar_index": 12,
            "features": {"atr_14": 25.0},
        },
        "reasoning": {
            "chain_id": "algo-chain",
            "steps": [],
            "conclusion": "algorithmic qualified long",
            "final_confidence": 0.72,
        },
        "decision": {
            "signal": "BUY",
            "confidence": 0.72,
            "position_size": 0.05,
        },
        "policy_verdict": verdict.model_dump(mode="json"),
    }


@pytest.mark.asyncio
async def test_algorithmic_path_scores_with_no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.core.mcp_orchestrator import MCPOrchestrator

    monkeypatch.setenv("TRANSFORMER_DECISION_PATH", ALGO_DECISION_PATH)
    orchestrator = MCPOrchestrator()
    orchestrator._initialized = True
    orchestrator.model_registry = MagicMock()
    orchestrator.model_registry.models = {}

    async def _fake(**_kwargs):
        return _verdict_result()

    monkeypatch.setattr(
        "agent.core.algorithmic_decision.evaluate_algorithmic_prediction",
        _fake,
    )
    result = await orchestrator.process_prediction_request("BTCUSD", {})
    assert result["error"] is None
    assert result["policy_verdict"]["signal"] == "BUY"
    assert result["market_context"]["decision_path"] == ALGO_DECISION_PATH


@pytest.mark.asyncio
async def test_fusion_path_still_requires_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.core.mcp_orchestrator import MCPOrchestrator

    monkeypatch.setenv("TRANSFORMER_DECISION_PATH", "mtf_fusion")
    orchestrator = MCPOrchestrator()
    orchestrator._initialized = True
    orchestrator.model_registry = MagicMock()
    orchestrator.model_registry.models = {}
    result = await orchestrator.process_prediction_request("BTCUSD", {})
    assert result["error_code"] == "NO_MODELS_REGISTERED"


def _trade() -> dict:
    return {
        "symbol": "BTCUSD",
        "side": "buy",
        "quantity": 1,
        "price": 100.0,
        "execution_authority": AGENT_DECISION_AUTHORITY,
        "algo_signal_validated": True,
        "ml_signal_validated": False,
    }


@pytest.mark.asyncio
async def test_algorithmic_orders_blocked_until_flag_is_enabled() -> None:
    from agent.core.execution import ExecutionEngine

    engine = ExecutionEngine()
    engine._initialized = True
    engine.exchange_connected = True
    with patch("agent.core.execution.settings") as mock_settings:
        mock_settings.agent_only_delta_orders = True
        mock_settings.block_manual_execute_trade = True
        mock_settings.require_ml_signal_for_orders = True
        mock_settings.algorithmic_orders_enabled = False
        blocked = await engine.execute_trade(_trade())
    assert not blocked.success
    assert "ALGORITHMIC_ORDERS_ENABLED" in (blocked.error_message or "")

    engine._validate_trade = AsyncMock(
        return_value={"valid": False, "error": "validation_reached"}
    )
    with patch("agent.core.execution.settings") as mock_settings:
        mock_settings.agent_only_delta_orders = True
        mock_settings.block_manual_execute_trade = True
        mock_settings.require_ml_signal_for_orders = True
        mock_settings.algorithmic_orders_enabled = True
        mock_settings.stop_loss_percentage = 0.01
        mock_settings.take_profit_percentage = 0.02
        mock_settings.atr_sl_distance_mult = 1.0
        mock_settings.atr_tp_distance_mult = 1.5
        allowed = await engine.execute_trade(_trade())
    assert allowed.error_message == "validation_reached"
