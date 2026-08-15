"""Path-pred SL/TP must reach Delta brackets without %/ATR overwrite."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.execution import ExecutionEngine


@pytest.fixture
def engine() -> ExecutionEngine:
    eng = ExecutionEngine()
    eng._initialized = True
    eng.exchange_connected = True
    eng.delta_client = MagicMock()
    eng.delta_client.create_position_bracket = AsyncMock(return_value={"success": True})
    eng.delta_client.find_open_bracket_order_id = AsyncMock(return_value=42)
    eng.delta_client.update_bracket_order = AsyncMock(return_value={"success": True})
    eng.position_manager = MagicMock()
    return eng


@pytest.mark.asyncio
async def test_attach_position_bracket_posts_planned_path_prices(engine, monkeypatch):
    monkeypatch.setattr(
        "agent.core.execution.settings",
        SimpleNamespace(
            use_delta_position_bracket_api=True,
            bracket_stop_trigger_method="mark_price",
            use_atr_trailing_stop=False,
            use_atr_scaled_sl_tp=False,
            sl_tp_mode="path_pred",
            stop_loss_percentage=0.01,
            take_profit_percentage=0.015,
            atr_sl_distance_mult=1.0,
            atr_tp_distance_mult=1.5,
            bracket_fallback_local_sl_tp=True,
        ),
    )
    # Rebased path-pred levels (not 1% / 1.5%)
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 100_050.0,
        "stop_loss": 99_050.0,
        "take_profit": 102_050.0,
        "sl_tp_source": "path_pred",
        "tick_size": 0.5,
        "status": "open",
    }

    await engine._attach_position_bracket(position, "BTCUSD", atr_14=500.0, regime="neutral")

    engine.delta_client.create_position_bracket.assert_awaited_once()
    kwargs = engine.delta_client.create_position_bracket.await_args.kwargs
    assert kwargs["stop_loss_order"]["stop_price"] == "99050.0"
    assert kwargs["take_profit_order"]["stop_price"] == "102050.0"
    # Must not overwrite planned prices with config % (100050 * 0.01 => 99049.5)
    assert position["stop_loss"] == 99_050.0
    assert position["take_profit"] == 102_050.0
    assert position["sl_tp_source"] == "path_pred"
    assert position["exchange_bracket_sl_tp"] is True


@pytest.mark.asyncio
async def test_maybe_update_dynamic_bracket_noop_for_path_pred(engine, monkeypatch):
    monkeypatch.setattr(
        "agent.core.execution.settings",
        SimpleNamespace(
            dynamic_sl_tp_enabled=True,
            use_delta_position_bracket_api=True,
            sl_tp_mode="path_pred",
            bracket_fallback_local_sl_tp=True,
        ),
    )
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 100_000.0,
        "stop_loss": 99_000.0,
        "take_profit": 102_000.0,
        "sl_tp_source": "path_pred",
        "status": "open",
        "atr_14": 800.0,
        "regime": "trending",
    }

    await engine._maybe_update_dynamic_bracket("BTCUSD", position)

    engine.delta_client.update_bracket_order.assert_not_awaited()
    engine.delta_client.create_position_bracket.assert_not_awaited()
    assert position["stop_loss"] == 99_000.0
    assert position["take_profit"] == 102_000.0


@pytest.mark.asyncio
async def test_update_bracket_stop_only_skips_path_pred(engine, monkeypatch):
    monkeypatch.setattr(
        "agent.core.execution.settings",
        SimpleNamespace(
            dynamic_sl_tp_enabled=True,
            use_delta_position_bracket_api=True,
            sl_tp_mode="path_pred",
            bracket_fallback_local_sl_tp=True,
        ),
    )
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 100_000.0,
        "stop_loss": 99_000.0,
        "take_profit": 102_000.0,
        "sl_tp_source": "path_pred",
        "status": "open",
        "bracket_order_id": 7,
    }
    engine.position_manager.get_position.return_value = position

    await engine._update_bracket_stop_only("BTCUSD", 99_500.0)

    engine.delta_client.update_bracket_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_attach_falls_back_when_both_levels_missing(engine, monkeypatch):
    monkeypatch.setattr(
        "agent.core.execution.settings",
        SimpleNamespace(
            use_delta_position_bracket_api=True,
            bracket_stop_trigger_method="mark_price",
            use_atr_trailing_stop=False,
            use_atr_scaled_sl_tp=False,
            sl_tp_mode="fixed",
            stop_loss_percentage=0.01,
            take_profit_percentage=0.02,
            atr_sl_distance_mult=1.0,
            atr_tp_distance_mult=1.5,
            bracket_fallback_local_sl_tp=True,
        ),
    )
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 100_000.0,
        "stop_loss": None,
        "take_profit": None,
        "status": "open",
    }

    await engine._attach_position_bracket(position, "BTCUSD")

    engine.delta_client.create_position_bracket.assert_awaited_once()
    assert position["stop_loss"] == 99_000.0
    assert position["take_profit"] == 102_000.0
    assert position["sl_tp_source"] == "fixed"
