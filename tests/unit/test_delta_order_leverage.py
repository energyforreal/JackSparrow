"""Unit tests for Delta Exchange order leverage API helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.data.delta_client import DeltaExchangeClient, DeltaExchangeError


@pytest.fixture
def client() -> DeltaExchangeClient:
    return DeltaExchangeClient()


@pytest.mark.asyncio
async def test_set_order_leverage_posts_string_body(client: DeltaExchangeClient) -> None:
    with patch.object(
        client, "_make_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {
            "success": True,
            "result": {"leverage": "10", "product_id": 27},
        }
        with patch.object(
            client, "_resolve_leverage_product_id", new_callable=AsyncMock, return_value=27
        ):
            await client.set_order_leverage(10, product_id=27)

    mock_req.assert_awaited_once()
    method, endpoint = mock_req.await_args.args[0], mock_req.await_args.args[1]
    assert method == "POST"
    assert endpoint == "/v2/products/27/orders/leverage"
    assert mock_req.await_args.kwargs["data"] == {"leverage": "10"}


@pytest.mark.asyncio
async def test_ensure_order_leverage_skips_post_when_get_matches(
    client: DeltaExchangeClient,
) -> None:
    with patch.object(
        client, "get_order_leverage", new_callable=AsyncMock
    ) as mock_get:
        with patch.object(
            client, "set_order_leverage", new_callable=AsyncMock
        ) as mock_set:
            with patch.object(
                client, "resolve_product_id", new_callable=AsyncMock, return_value=27
            ):
                mock_get.return_value = {
                    "success": True,
                    "result": {"leverage": "5", "product_id": 27},
                }
                result = await client.ensure_order_leverage("BTCUSD", 5)

    mock_get.assert_awaited_once()
    mock_set.assert_not_awaited()
    assert client._parse_order_leverage_value(result) == 5


@pytest.mark.asyncio
async def test_ensure_order_leverage_posts_when_get_differs(
    client: DeltaExchangeClient,
) -> None:
    with patch.object(
        client, "get_order_leverage", new_callable=AsyncMock
    ) as mock_get:
        with patch.object(
            client, "set_order_leverage", new_callable=AsyncMock
        ) as mock_set:
            with patch.object(
                client, "resolve_product_id", new_callable=AsyncMock, return_value=27
            ):
                mock_get.return_value = {
                    "success": True,
                    "result": {"leverage": "3", "product_id": 27},
                }
                mock_set.return_value = {
                    "success": True,
                    "result": {"leverage": "10", "product_id": 27},
                }
                await client.ensure_order_leverage("BTCUSD", 10)

    mock_set.assert_awaited_once_with(10, product_id=27)


@pytest.mark.asyncio
async def test_parse_order_leverage_value() -> None:
    assert DeltaExchangeClient._parse_order_leverage_value(
        {"result": {"leverage": "12"}}
    ) == 12
    assert DeltaExchangeClient._parse_order_leverage_value({}) is None


@pytest.mark.asyncio
async def test_ensure_order_leverage_raises_on_mismatch(
    client: DeltaExchangeClient,
) -> None:
    with patch.object(
        client, "get_order_leverage", new_callable=AsyncMock, side_effect=DeltaExchangeError("no lev")
    ):
        with patch.object(
            client, "set_order_leverage", new_callable=AsyncMock
        ) as mock_set:
            with patch.object(
                client, "resolve_product_id", new_callable=AsyncMock, return_value=27
            ):
                mock_set.return_value = {
                    "success": True,
                    "result": {"leverage": "3", "product_id": 27},
                }
                with pytest.raises(DeltaExchangeError, match="mismatch"):
                    await client.ensure_order_leverage("BTCUSD", 10)
