"""Unit tests for limit entry and exit trigger labeling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.trade_lifecycle_engine import (
    _resolve_exit_trigger_and_detail,
    evaluate_lifecycle,
)
from tests.unit.test_trade_lifecycle_engine import (
    _live_mc,
    _position,
    _snapshot,
    mock_settings,
)


def test_resolve_exit_trigger_fsm_only() -> None:
    trigger, detail, flags = _resolve_exit_trigger_and_detail(
        opposite=False,
        opp_reason="",
        health=82.0,
        exit_max=50.0,
        fsm_broken=True,
    )
    assert trigger == "fsm_broken"
    assert detail == "fsm_thesis_broken"
    assert flags["fsm_thesis_broken"] is True
    assert flags["health_below_exit_max"] is False


def test_resolve_exit_trigger_opposite_wins() -> None:
    trigger, detail, flags = _resolve_exit_trigger_and_detail(
        opposite=True,
        opp_reason="opposite_entry_signal",
        health=30.0,
        exit_max=50.0,
        fsm_broken=True,
    )
    assert trigger == "opposite_signal"
    assert detail == "opposite_entry_signal"


@pytest.mark.asyncio
async def test_limit_entry_fallback_when_signal_invalid(monkeypatch) -> None:
    from agent.core.execution import ExecutionEngine

    engine = ExecutionEngine.__new__(ExecutionEngine)
    engine.delta_client = MagicMock()
    monkeypatch.setattr(
        "agent.core.execution.settings",
        MagicMock(
            entry_limit_timeout_seconds=0.1,
            entry_limit_post_only=True,
            entry_limit_max_reprices=0,
            entry_limit_reprice_enabled=False,
            entry_limit_revalidate_signal=True,
            entry_limit_fallback_to_market=True,
        ),
    )

    async def fake_place(**kwargs):
        return {
            "success": True,
            "order_id": "abc",
            "exchange_order_id": 1,
            "filled_immediately": False,
            "filled_quantity": 0,
        }

    engine._place_order = AsyncMock(side_effect=fake_place)
    engine._poll_order_fill_status = AsyncMock(return_value=(0.0, None, "open"))
    engine.cancel_order = AsyncMock(return_value=True)

    trade = {"signal_still_valid": False, "position_extras": {}}
    result = await engine._execute_limit_entry_with_fallback(
        trade,
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        stop_loss=90.0,
        take_profit=110.0,
        reference_price=100.0,
        idempotency_key="k1",
    )
    assert result["success"] is False
    assert result.get("limit_entry_abandoned") is True
    assert engine._place_order.await_count == 1
