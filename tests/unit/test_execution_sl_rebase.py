"""Unit tests for SL/TP rebase at fill in execute_trade."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.execution import ExecutionEngine, ExecutionResult


@pytest.mark.asyncio
async def test_execute_trade_rebases_stop_to_fill_before_open() -> None:
    engine = ExecutionEngine()
    engine._initialized = True
    engine.exchange_connected = True
    engine.delta_client = MagicMock()
    engine.position_manager = MagicMock()
    engine._inflight_lock = __import__("asyncio").Lock()
    engine._inflight_symbols = set()

    opened: dict = {}

    def _open_position(**kwargs):
        opened.update(kwargs)
        return {"symbol": kwargs["symbol"], "status": "open"}

    engine.position_manager.get_position.return_value = None
    engine.position_manager.open_position.side_effect = _open_position

    async def _place_order(**kwargs):
        return {
            "success": True,
            "order_id": "abcd1234",
            "filled_immediately": True,
            "average_fill_price": 100_050.0,
            "exchange_order_id": 99,
        }

    engine._place_order = AsyncMock(side_effect=_place_order)
    engine._validate_trade = AsyncMock(return_value={"valid": True})

    trade = {
        "symbol": "BTCUSD",
        "side": "buy",
        "quantity": 1.0,
        "order_type": "market",
        "price": 100_000.0,
        "reference_price": 100_000.0,
        "stop_loss": 99_000.0,
        "take_profit": 102_000.0,
        "execution_authority": "agent_decision",
        "ml_signal_validated": True,
    }

    with patch("agent.core.execution.is_agent_controlled_authority", return_value=True):
        with patch("agent.core.execution.record_decision_execution"):
            result = await engine.execute_trade(trade)

    assert result.success is True
    assert opened["stop_loss"] == 99_050.0
    assert opened["take_profit"] == 102_050.0
