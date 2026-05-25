"""Unit tests for exchange-native limit/stop order routing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.execution import ExecutionEngine


@pytest.fixture
def engine_with_delta():
    engine = ExecutionEngine()
    engine._initialized = True
    engine.delta_client = AsyncMock()
    engine.delta_client.place_order = AsyncMock(
        return_value={
            "success": True,
            "result": {
                "id": 42,
                "state": "open",
                "limit_price": "79000",
            },
        }
    )
    return engine


@pytest.mark.asyncio
async def test_place_limit_order_calls_delta(engine_with_delta):
    result = await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="limit",
        price=79000.0,
    )

    assert result["success"] is True
    engine_with_delta.delta_client.place_order.assert_awaited_once()
    kwargs = engine_with_delta.delta_client.place_order.await_args.kwargs
    assert kwargs["order_type"] == "LIMIT"
    assert kwargs["price"] == 79000.0
    assert kwargs.get("stop_price") is None


@pytest.mark.asyncio
async def test_place_stop_order_calls_delta_with_stop_price(engine_with_delta):
    result = await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="sell",
        quantity=1.0,
        order_type="stop",
        stop_price=78000.0,
        reduce_only=True,
    )

    assert result["success"] is True
    kwargs = engine_with_delta.delta_client.place_order.await_args.kwargs
    assert kwargs["order_type"] == "MARKET"
    assert kwargs["stop_price"] == 78000.0
    assert kwargs["reduce_only"] is True


@pytest.mark.asyncio
async def test_place_limit_order_requires_price(engine_with_delta):
    result = await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="limit",
        price=None,
    )

    assert result["success"] is False
    assert "price" in (result.get("error") or "").lower()
    engine_with_delta.delta_client.place_order.assert_not_awaited()
