"""Unit tests for MarketDataManager factory and buffer sharing."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.config import settings
from agent.data.market_data_manager import MarketDataManager, create_market_data_layer
from agent.data.market_data_service import MarketDataService


def _fake_candles(n: int = 50) -> list[dict]:
    base = int(datetime.now(timezone.utc).timestamp()) - n * 300
    out = []
    for i in range(n):
        ts = base + i * 300
        px = 100.0 + i * 0.1
        out.append(
            {
                "time": ts,
                "open": px,
                "high": px + 1,
                "low": px - 1,
                "close": px,
                "volume": 10.0,
            }
        )
    return out


def test_create_market_data_layer_returns_manager_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "market_data_manager_enabled", True)
    client = MagicMock()
    layer = create_market_data_layer(delta_client=client)
    assert isinstance(layer, MarketDataManager)
    assert layer.delta_client is client


def test_create_market_data_layer_returns_service_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "market_data_manager_enabled", False)
    client = MagicMock()
    layer = create_market_data_layer(delta_client=client)
    assert isinstance(layer, MarketDataService)
    assert not isinstance(layer, MarketDataManager)
    assert layer.delta_client is client


@pytest.mark.asyncio
async def test_orchestrator_and_feature_server_share_manager() -> None:
    """Single MarketDataManager instance is shared across MCP components."""
    from agent.core.mcp_orchestrator import MCPOrchestrator
    from agent.data.feature_server import MCPFeatureServer

    client = MagicMock()
    mgr = MarketDataManager(delta_client=client)
    fs = MCPFeatureServer(market_data_service=mgr)
    orch = MCPOrchestrator()
    orch.market_data_manager = mgr
    orch.feature_server = fs

    assert fs.market_data_service is mgr
    assert orch.market_data_manager is mgr
    assert orch.feature_server.market_data_service.ohlcv_buffers is mgr.ohlcv_buffers


@pytest.mark.asyncio
async def test_get_market_data_prefers_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Buffered OHLCV should satisfy get_market_data without REST when sufficient."""
    monkeypatch.setattr(settings, "market_data_manager_enabled", True)

    candles = _fake_candles(100)
    client = MagicMock()
    client.get_candles = AsyncMock(return_value={"result": {"candles": candles}})
    client.get_ticker = AsyncMock(return_value={"close": 101.0})

    mgr = MarketDataManager(delta_client=client)
    await mgr.get_ohlcv_df("BTCUSD", "5m", 50)
    calls_after_seed = client.get_candles.await_count

    await mgr.get_market_data("BTCUSD", interval="5m", limit=40)
    assert client.get_candles.await_count == calls_after_seed


@pytest.mark.asyncio
async def test_get_market_data_force_refresh_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    """force_refresh=True must bypass in-process buffer and hit the exchange."""
    monkeypatch.setattr(settings, "market_data_manager_enabled", True)

    candles = _fake_candles(100)
    client = MagicMock()
    client.get_candles = AsyncMock(return_value={"result": {"candles": candles}})
    client.get_ticker = AsyncMock(return_value={"close": 101.0})

    mgr = MarketDataManager(delta_client=client)
    await mgr.get_ohlcv_df("BTCUSD", "5m", 50)
    calls_after_seed = client.get_candles.await_count

    await mgr.get_market_data("BTCUSD", interval="5m", limit=40, force_refresh=True)
    assert client.get_candles.await_count > calls_after_seed
