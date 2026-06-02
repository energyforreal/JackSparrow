"""Unit tests for Delta position bracket client helpers."""

import pytest
from unittest.mock import AsyncMock

from agent.data.delta_client import DeltaExchangeClient


@pytest.mark.asyncio
async def test_create_position_bracket_posts_nested_orders():
    client = DeltaExchangeClient()
    client._make_request = AsyncMock(return_value={"success": True})  # type: ignore[method-assign]
    client.resolve_product_id = AsyncMock(return_value=84)  # type: ignore[method-assign]

    await client.create_position_bracket(
        "BTCUSD",
        stop_loss_order={"order_type": "market_order", "stop_price": "99000"},
        take_profit_order={"order_type": "market_order", "stop_price": "102000"},
        bracket_stop_trigger_method="mark_price",
        use_product_symbol_only=True,
    )

    client._make_request.assert_awaited_once()
    args, kwargs = client._make_request.await_args
    assert args[0] == "POST"
    assert args[1] == "/v2/orders/bracket"
    data = kwargs["data"]
    assert data["product_symbol"] == "BTCUSD"
    assert data["stop_loss_order"]["stop_price"] == "99000"


@pytest.mark.asyncio
async def test_find_open_bracket_order_id():
    client = DeltaExchangeClient()
    client.resolve_product_id = AsyncMock(return_value=84)  # type: ignore[method-assign]
    client._make_request = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "result": [
                {"id": 99, "product_symbol": "BTCUSD", "bracket_stop_loss_price": "1"},
                {"id": 100, "product_symbol": "ETHUSD"},
            ]
        }
    )

    oid = await client.find_open_bracket_order_id("BTCUSD")
    assert oid == 99
