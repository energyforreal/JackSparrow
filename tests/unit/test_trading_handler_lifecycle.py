"""Unit tests for TradingEventHandler Trade Lifecycle integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.trade_lifecycle_engine import LifecycleVerdict
from agent.events.handlers.trading_handler import TradingEventHandler
from agent.events.schemas import DecisionReadyEvent


@pytest.fixture
def handler() -> TradingEventHandler:
    h = TradingEventHandler(MagicMock())
    h.execution_module = MagicMock()
    h.execution_module.position_manager = MagicMock()
    h.learning_system = MagicMock()
    h.learning_system.calibrate_runtime_confidence = AsyncMock(
        side_effect=lambda c, _: c
    )
    return h


@pytest.mark.asyncio
async def test_lifecycle_exit_closes_position(handler: TradingEventHandler) -> None:
    handler.execution_module.position_manager.get_position.return_value = {
        "symbol": "BTCUSD",
        "side": "long",
        "status": "open",
        "conviction_at_entry": 0.8,
        "take_profit": 105.0,
        "entry_decision_snapshot": {"decision_context": {"features": {}}},
    }
    handler.execution_module.close_position = AsyncMock(
        return_value=MagicMock(success=True)
    )

    verdict = LifecycleVerdict(
        action="EXIT",
        health_score=40.0,
        opportunity_score=30.0,
        conviction_now=0.5,
        conviction_at_entry=0.8,
        conviction_delta=-0.3,
        exit_reason_detail="opposite_entry_signal",
    )

    with patch("agent.events.handlers.trading_handler.settings") as s:
        s.trade_lifecycle_enabled = True
        s.exchange_position_reconcile_enabled = False
        with patch(
            "agent.core.trade_lifecycle_engine.evaluate_lifecycle",
            return_value=verdict,
        ):
            result = await handler._run_trade_lifecycle_if_positioned(
                symbol="BTCUSD",
                event_id="evt-1",
                payload={"policy_verdict": {"signal": "HOLD", "conviction": 0.5}},
                mc={"signal": "HOLD", "policy_verdict": {"signal": "HOLD"}},
                signal="HOLD",
            )

    assert result is True
    handler.execution_module.close_position.assert_awaited_once_with(
        "BTCUSD", exit_reason="lifecycle_exit"
    )


@pytest.mark.asyncio
async def test_lifecycle_exit_fall_through_on_reversal_entry(
    handler: TradingEventHandler,
) -> None:
    handler.execution_module.position_manager.get_position.return_value = {
        "symbol": "BTCUSD",
        "side": "long",
        "status": "open",
        "entry_decision_snapshot": {"decision_context": {"features": {}}},
    }
    handler.execution_module.close_position = AsyncMock(
        return_value=MagicMock(success=True)
    )
    verdict = LifecycleVerdict(
        action="EXIT",
        health_score=40.0,
        opportunity_score=30.0,
        conviction_now=0.5,
        conviction_at_entry=0.8,
        conviction_delta=-0.3,
        exit_reason_detail="opposite_entry_signal",
    )

    with patch("agent.events.handlers.trading_handler.settings") as s:
        s.trade_lifecycle_enabled = True
        s.exchange_position_reconcile_enabled = False
        with patch(
            "agent.core.trade_lifecycle_engine.evaluate_lifecycle",
            return_value=verdict,
        ):
            result = await handler._run_trade_lifecycle_if_positioned(
                symbol="BTCUSD",
                event_id="evt-1b",
                payload={"policy_verdict": {"signal": "SELL", "conviction": 0.5}},
                mc={"signal": "SELL"},
                signal="SELL",
            )

    assert result == "fall_through"


@pytest.mark.asyncio
async def test_lifecycle_modify_tp(handler: TradingEventHandler) -> None:
    handler.execution_module.position_manager.get_position.return_value = {
        "symbol": "BTCUSD",
        "side": "long",
        "status": "open",
        "conviction_at_entry": 0.8,
        "take_profit": 105.0,
        "entry_decision_snapshot": {"decision_context": {"features": {}}},
    }
    handler.execution_module.apply_lifecycle_modify_tp = AsyncMock(
        return_value={"success": True}
    )

    verdict = LifecycleVerdict(
        action="MODIFY_TP",
        health_score=85.0,
        opportunity_score=88.0,
        conviction_now=0.92,
        conviction_at_entry=0.8,
        conviction_delta=0.12,
        new_take_profit=110.0,
        tp_direction="extend",
    )

    with patch("agent.events.handlers.trading_handler.settings") as s:
        s.trade_lifecycle_enabled = True
        s.exchange_position_reconcile_enabled = False
        with patch(
            "agent.core.trade_lifecycle_engine.evaluate_lifecycle",
            return_value=verdict,
        ):
            result = await handler._run_trade_lifecycle_if_positioned(
                symbol="BTCUSD",
                event_id="evt-2",
                payload={},
                mc={"policy_verdict": {"signal": "HOLD", "conviction": 0.92}},
                signal="HOLD",
            )

    assert result is True
    handler.execution_module.apply_lifecycle_modify_tp.assert_awaited_once_with(
        "BTCUSD", 110.0, "extend"
    )


@pytest.mark.asyncio
async def test_lifecycle_skipped_when_disabled(handler: TradingEventHandler) -> None:
    with patch("agent.events.handlers.trading_handler.settings") as s:
        s.trade_lifecycle_enabled = False
        result = await handler._run_trade_lifecycle_if_positioned(
            symbol="BTCUSD",
            event_id="evt-3",
            payload={},
            mc={},
            signal="HOLD",
        )
    assert result is False
