"""Unit tests for live-mode execution routing to Delta exchange APIs."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.execution import ExecutionEngine


@pytest.fixture
def live_engine():
    engine = ExecutionEngine()
    engine._initialized = True
    engine.exchange_connected = True
    engine.delta_client = AsyncMock()
    engine.delta_client.resolve_product_id = AsyncMock(return_value=84)
    engine.delta_client.place_order = AsyncMock(
        return_value={
            "success": True,
            "result": {
                "id": 999,
                "state": "closed",
                "average_fill_price": "80000",
            },
        }
    )
    engine.delta_client.cancel_order = AsyncMock(return_value={"success": True})
    engine.delta_client.cancel_all_orders = AsyncMock(return_value={"success": True})
    engine.risk_manager = MagicMock()
    engine.position_manager.get_position = MagicMock(
        return_value={
            "status": "open",
            "side": "long",
            "entry_price": 79000.0,
            "lots": 1,
            "quantity": 1,
            "contract_value_btc": 0.001,
        }
    )
    engine.position_manager.close_position = MagicMock(
        return_value={"symbol": "BTCUSD", "realized_pnl": 10.0}
    )
    return engine


@pytest.mark.asyncio
async def test_close_position_uses_reduce_only(live_engine):
    with patch.object(live_engine, "_place_order", new_callable=AsyncMock) as mock_place:
        mock_place.return_value = {
            "success": True,
            "order_id": "test-ord",
            "filled_immediately": True,
            "average_fill_price": 80000.0,
        }
        result = await live_engine.close_position("BTCUSD", exit_reason="signal_reversal")

    assert result.success is True
    mock_place.assert_awaited_once()
    assert mock_place.await_args.kwargs.get("reduce_only") is True


@pytest.mark.asyncio
async def test_cancel_order_calls_exchange(live_engine):
    order = MagicMock()
    order.symbol = "BTCUSD"
    order.exchange_order_id = 12345
    live_engine.order_manager.get_order = MagicMock(return_value=order)
    live_engine.order_manager.cancel_order = MagicMock(return_value=True)

    ok = await live_engine.cancel_order("local-1", symbol="BTCUSD")

    assert ok is True
    live_engine.delta_client.cancel_order.assert_awaited_once_with(12345, product_id=84)


@pytest.mark.asyncio
async def test_cancel_all_orders_calls_exchange(live_engine):
    result = await live_engine.cancel_all_orders("BTCUSD")

    assert result["success"] is True
    live_engine.delta_client.cancel_all_orders.assert_awaited_once_with(product_id=84)
