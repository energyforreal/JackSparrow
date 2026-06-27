"""Tests for startup candle cache seeding (no replay on boot)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.data.market_data_service import MarketDataService


@pytest.mark.asyncio
async def test_seed_last_completed_candle_cache_sets_second_to_last() -> None:
    svc = MarketDataService()
    candles = [
        {"timestamp": 1000, "close": 1.0},
        {"timestamp": 2000, "close": 2.0},
        {"timestamp": 3000, "close": 3.0},
    ]
    with patch.object(
        svc,
        "get_market_data",
        new=AsyncMock(return_value={"candles": candles}),
    ):
        await svc.seed_last_completed_candle_cache(["BTCUSD"], "5m")

    assert svc._last_candle_cache["BTCUSD:5m"]["timestamp"] == 2000


@pytest.mark.asyncio
async def test_check_and_emit_candle_skips_when_cache_seeded() -> None:
    svc = MarketDataService()
    candles = [
        {"timestamp": 1000, "close": 1.0},
        {"timestamp": 2000, "close": 2.0},
        {"timestamp": 3000, "close": 3.0},
    ]
    svc._last_candle_cache["BTCUSD:5m"] = candles[-2]

    with patch.object(
        svc,
        "get_market_data",
        new=AsyncMock(return_value={"candles": candles}),
    ), patch.object(
        svc,
        "_on_candle_close",
        new=AsyncMock(),
    ) as mock_close:
        await svc._check_and_emit_candle("BTCUSD", "5m")

    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_seed_skips_when_insufficient_candles() -> None:
    svc = MarketDataService()
    with patch.object(
        svc,
        "get_market_data",
        new=AsyncMock(return_value={"candles": [{"timestamp": 1}]}),
    ):
        await svc.seed_last_completed_candle_cache(["BTCUSD"], "5m")

    assert "BTCUSD:5m" not in svc._last_candle_cache
