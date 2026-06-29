"""Unit tests for Trade Lifecycle execution TP/SL helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.execution import ExecutionEngine


@pytest.fixture
def engine() -> ExecutionEngine:
    eng = ExecutionEngine()
    eng._initialized = True
    eng.delta_client = MagicMock()
    eng.delta_client.find_open_bracket_order_id = AsyncMock(return_value=42)
    eng.delta_client.update_bracket_order = AsyncMock()
    eng._position_lock = __import__("asyncio").Lock()
    eng.position_manager = MagicMock()
    return eng


@pytest.mark.asyncio
async def test_apply_lifecycle_modify_tp_extend_long(engine: ExecutionEngine) -> None:
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "status": "open",
        "entry_price": 100.0,
        "current_price": 104.0,
        "take_profit": 105.0,
        "exchange_bracket_sl_tp": True,
        "bracket_order_id": 42,
    }
    engine.position_manager.get_position.return_value = position

    with patch("agent.core.execution.settings") as mock_settings:
        mock_settings.order_persistence_enabled = False
        mock_settings.dynamic_sl_tp_enabled = True
        mock_settings.use_delta_position_bracket_api = True
        mock_settings.bracket_stop_trigger_method = "mark_price"
        mock_settings.bracket_fallback_local_sl_tp = True

        result = await engine.apply_lifecycle_modify_tp("BTCUSD", 108.0, "extend")

    assert result["success"] is True
    assert result["tp_before"] == 105.0
    assert result["tp_after"] == 108.0
    assert position["take_profit"] == 108.0
    engine.delta_client.update_bracket_order.assert_awaited()


@pytest.mark.asyncio
async def test_apply_lifecycle_modify_tp_reject_extend_down(engine: ExecutionEngine) -> None:
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "status": "open",
        "entry_price": 100.0,
        "current_price": 104.0,
        "take_profit": 105.0,
    }
    engine.position_manager.get_position.return_value = position

    with patch("agent.core.execution.settings") as mock_settings:
        mock_settings.order_persistence_enabled = False

        result = await engine.apply_lifecycle_modify_tp("BTCUSD", 104.5, "extend")

    assert result["success"] is False
    assert result["reason"] == "extend_violates_ratchet"


@pytest.mark.asyncio
async def test_apply_lifecycle_tighten_long(engine: ExecutionEngine) -> None:
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "status": "open",
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "exchange_bracket_sl_tp": True,
        "bracket_order_id": 42,
    }
    engine.position_manager.get_position.return_value = position

    with patch("agent.core.execution.settings") as mock_settings:
        mock_settings.order_persistence_enabled = False
        mock_settings.dynamic_sl_tp_enabled = True
        mock_settings.use_delta_position_bracket_api = True
        mock_settings.bracket_stop_trigger_method = "mark_price"
        mock_settings.bracket_fallback_local_sl_tp = True

        result = await engine.apply_lifecycle_tighten("BTCUSD", 99.5)

    assert result["success"] is True
    assert position["stop_loss"] == 99.5
