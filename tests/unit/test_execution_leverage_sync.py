"""Unit tests for exchange order leverage sync before entry orders."""

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
    engine.delta_client.ensure_order_leverage = AsyncMock(
        return_value={"success": True, "result": {"leverage": "5", "product_id": 27}}
    )
    engine.delta_client.place_order = AsyncMock(
        return_value={
            "success": True,
            "result": {
                "id": 99,
                "state": "closed",
                "average_fill_price": "80000",
                "size": 1,
            },
        }
    )
    return engine


@pytest.mark.asyncio
async def test_place_order_syncs_leverage_before_entry(engine_with_delta):
    result = await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="market",
        leverage=8,
    )

    assert result["success"] is True
    engine_with_delta.delta_client.ensure_order_leverage.assert_awaited_once_with(
        "BTCUSD", 8
    )
    engine_with_delta.delta_client.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_place_order_aborts_when_leverage_sync_fails(engine_with_delta):
    engine_with_delta.delta_client.ensure_order_leverage = AsyncMock(
        side_effect=RuntimeError("open position blocks leverage change")
    )

    result = await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="market",
        leverage=10,
    )

    assert result["success"] is False
    assert "leverage" in (result.get("error") or "").lower()
    engine_with_delta.delta_client.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_order_skips_leverage_sync_for_reduce_only(engine_with_delta):
    result = await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="sell",
        quantity=1.0,
        order_type="market",
        reduce_only=True,
        leverage=10,
    )

    assert result["success"] is True
    engine_with_delta.delta_client.ensure_order_leverage.assert_not_awaited()
    engine_with_delta.delta_client.place_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_place_order_skips_leverage_sync_when_leverage_omitted(
    engine_with_delta,
):
    await engine_with_delta._place_order(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="market",
    )

    engine_with_delta.delta_client.ensure_order_leverage.assert_not_awaited()
    engine_with_delta.delta_client.place_order.assert_awaited_once()
