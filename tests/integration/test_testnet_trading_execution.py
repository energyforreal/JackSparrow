"""
Integration tests for Delta testnet execution path (mocked exchange API).
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
os.environ.setdefault("TRADING_MODE", "testnet")
os.environ.setdefault("DELTA_ENV", "india_testnet")

from agent.core.execution import execution_module


@pytest.fixture
def mock_delta_client():
    client = MagicMock()
    client.place_order = AsyncMock(
        return_value={
            "result": {
                "order": {
                    "id": 12345,
                    "average_fill_price": "50000.0",
                    "state": "closed",
                }
            }
        }
    )
    client.get_ticker = AsyncMock()
    return client


@pytest.fixture
def exec_module(mock_delta_client):
    execution_module.delta_client = mock_delta_client
    execution_module._initialized = True
    execution_module.exchange_connected = True
    execution_module.position_manager.positions.clear()
    return execution_module


@pytest.fixture(autouse=True)
def reset_execution_positions(exec_module):
    exec_module.position_manager.positions.clear()
    yield
    exec_module.position_manager.positions.clear()


@pytest.mark.asyncio
async def test_place_order_calls_delta_testnet_api(exec_module, mock_delta_client):
    result = await exec_module._place_order(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="market",
        price=50000.0,
    )
    assert result["success"] is True
    assert result["average_fill_price"] == 50000.0
    mock_delta_client.place_order.assert_awaited_once()
    kwargs = mock_delta_client.place_order.await_args.kwargs
    assert kwargs["symbol"] == "BTCUSD"
    assert kwargs["side"] == "BUY"
    assert kwargs["order_type"] == "MARKET"


@pytest.mark.asyncio
async def test_close_order_uses_reduce_only(exec_module, mock_delta_client):
    exec_module.position_manager.open_position(
        symbol="BTCUSD",
        side="long",
        quantity=1.0,
        entry_price=50000.0,
        order_id="open1",
    )
    await exec_module.close_position("BTCUSD", order_type="market")
    mock_delta_client.place_order.assert_awaited()
    kwargs = mock_delta_client.place_order.await_args.kwargs
    assert kwargs.get("reduce_only") is True
