"""Tests for MarketDataService.get_health public API."""

from __future__ import annotations

from datetime import datetime, timezone

from agent.data.market_data_service import MarketDataService


def test_get_health_reports_streaming_flags() -> None:
    svc = MarketDataService()
    svc._websocket_connected = True
    svc.streaming_running = False
    health = svc.get_health("BTCUSD")
    assert health["websocket_connected"] is True
    assert health["streaming_running"] is False
    assert health["healthy"] is True


def test_get_health_ticker_recent() -> None:
    svc = MarketDataService()
    svc._last_tick_time["BTCUSD"] = datetime.now(timezone.utc)
    health = svc.get_health("BTCUSD")
    assert health["ticker_recent"] is True
    assert health["healthy"] is True
