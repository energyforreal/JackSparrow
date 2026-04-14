"""Unit tests for Delta market data stale REST fallback and symbol normalization."""

import time
from unittest.mock import AsyncMock

import pytest

from agent.data.symbols import normalize_symbol_for_delta_api
from agent.data.market_data_service import MarketDataService


def test_normalize_symbol_for_delta_api_strips_p_suffix():
    assert normalize_symbol_for_delta_api("BTCUSD.P") == "BTCUSD"
    assert normalize_symbol_for_delta_api("BTCUSD") == "BTCUSD"
    assert normalize_symbol_for_delta_api("") == ""


def test_ticker_stale_true_when_no_tick_yet():
    mds = MarketDataService()
    assert mds._ticker_stale("BTCUSD") is True


def test_ticker_stale_false_when_recent_good_tick(monkeypatch):
    mds = MarketDataService()
    monkeypatch.setattr(
        "agent.data.market_data_service.settings",
        type(
            "S",
            (),
            {"market_data_stale_rest_poll_seconds": 60.0},
        )(),
        raising=False,
    )
    # Patch settings on module - cleaner: use real settings and set attribute
    from agent.core import config as config_module

    prev = config_module.settings.market_data_stale_rest_poll_seconds
    try:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            60.0,
        )
        mds._last_good_tick_monotonic["BTCUSD"] = time.monotonic()
        assert mds._ticker_stale("BTCUSD") is False
    finally:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            prev,
        )


def test_ticker_stale_true_when_old_tick(monkeypatch):
    mds = MarketDataService()
    from agent.core import config as config_module

    prev = config_module.settings.market_data_stale_rest_poll_seconds
    try:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            1.0,
        )
        mds._last_good_tick_monotonic["BTCUSD"] = time.monotonic() - 10.0
        assert mds._ticker_stale("BTCUSD") is True
    finally:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            prev,
        )


@pytest.mark.asyncio
async def test_poll_ticker_via_rest_when_stale_triggers_check(monkeypatch):
    mds = MarketDataService()
    mds._websocket_enabled = True
    mds._websocket_connected = True
    mds._ws_ticker_subscription_ok = True
    mds._last_good_tick_monotonic["BTCUSD"] = time.monotonic() - 9999.0

    mock_check = AsyncMock()
    mds._check_and_emit_ticker_with_fluctuation = mock_check

    from agent.core import config as config_module

    prev = config_module.settings.market_data_stale_rest_poll_seconds
    try:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            15.0,
        )
        await mds._poll_ticker_via_rest_if_needed("BTCUSD")
    finally:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            prev,
        )

    mock_check.assert_awaited_once_with("BTCUSD")


@pytest.mark.asyncio
async def test_poll_ticker_skips_when_ws_trusted_and_fresh(monkeypatch):
    mds = MarketDataService()
    mds._websocket_enabled = True
    mds._websocket_connected = True
    mds._ws_ticker_subscription_ok = True
    mds._last_good_tick_monotonic["BTCUSD"] = time.monotonic()

    mock_check = AsyncMock()
    mds._check_and_emit_ticker_with_fluctuation = mock_check

    from agent.core import config as config_module

    prev = config_module.settings.market_data_stale_rest_poll_seconds
    try:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            60.0,
        )
        await mds._poll_ticker_via_rest_if_needed("BTCUSD")
    finally:
        object.__setattr__(
            config_module.settings,
            "market_data_stale_rest_poll_seconds",
            prev,
        )

    mock_check.assert_not_called()


def test_price_from_delta_wss_message_precedence():
    assert (
        MarketDataService._price_from_delta_wss_message(
            {"mark_price": 100.0, "close": 99.0, "spot_price": 98.0}
        )
        == 100.0
    )
    assert (
        MarketDataService._price_from_delta_wss_message(
            {"close": 99.0, "spot_price": 98.0}
        )
        == 99.0
    )
    assert (
        MarketDataService._price_from_delta_wss_message(
            {"spot_price": 98.0}
        )
        == 98.0
    )
    assert MarketDataService._price_from_delta_wss_message({"mark_price": 0}) == 0.0


def test_on_delta_ws_connection_lost_clears_flags():
    mds = MarketDataService()
    mds._ws_ticker_subscription_ok = True
    mds._websocket_connected = True
    mds._on_delta_ws_connection_lost("connection_closed")
    assert mds._ws_ticker_subscription_ok is False
    assert mds._websocket_connected is False
