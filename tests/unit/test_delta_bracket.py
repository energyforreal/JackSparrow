"""Unit tests for Delta position bracket client helpers."""

import pytest
from unittest.mock import AsyncMock

from agent.data.delta_client import (
    DeltaExchangeClient,
    parse_bracket_id_from_api_response,
    pick_bracket_order_id_from_rows,
)


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
async def test_find_open_bracket_order_id_legacy_bracket_fields():
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
    call_kwargs = client._make_request.await_args.kwargs
    assert call_kwargs["params"]["states"] == "open,pending"


@pytest.mark.asyncio
async def test_find_open_bracket_order_id_pending_stop_loss_leg():
    client = DeltaExchangeClient()
    client.resolve_product_id = AsyncMock(return_value=84)  # type: ignore[method-assign]
    client._make_request = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "result": [
                {
                    "id": 257702521,
                    "product_symbol": "BTCUSD",
                    "state": "pending",
                    "stop_order_type": "stop_loss_order",
                    "reduce_only": True,
                },
                {
                    "id": 257702522,
                    "product_symbol": "BTCUSD",
                    "state": "pending",
                    "stop_order_type": "take_profit_order",
                    "reduce_only": True,
                },
            ]
        }
    )

    oid = await client.find_open_bracket_order_id("BTCUSD")
    assert oid == 257702521


def test_pick_bracket_order_id_prefers_stop_loss_leg():
    rows = [
        {
            "id": 200,
            "product_symbol": "BTCUSD",
            "stop_order_type": "take_profit_order",
            "state": "pending",
        },
        {
            "id": 100,
            "product_symbol": "BTCUSD",
            "stop_order_type": "stop_loss_order",
            "state": "pending",
        },
    ]
    assert pick_bracket_order_id_from_rows(rows, "BTCUSD") == 100


def test_parse_bracket_id_from_nested_result():
    resp = {"success": True, "result": {"id": 34521712}}
    assert parse_bracket_id_from_api_response(resp) == 34521712


@pytest.mark.asyncio
async def test_resolve_bracket_order_id_uses_create_response():
    client = DeltaExchangeClient()
    client.find_open_bracket_order_id = AsyncMock(return_value=None)  # type: ignore[method-assign]

    oid = await client.resolve_bracket_order_id(
        "BTCUSD",
        create_response={"result": {"id": 42}},
        retries=1,
    )
    assert oid == 42
    client.find_open_bracket_order_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_bracket_order_id_retries_get():
    client = DeltaExchangeClient()
    client.find_open_bracket_order_id = AsyncMock(side_effect=[None, 77])  # type: ignore[method-assign]

    oid = await client.resolve_bracket_order_id("BTCUSD", retries=2, delay_s=0)
    assert oid == 77
    assert client.find_open_bracket_order_id.await_count == 2
