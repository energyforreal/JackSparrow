"""Unit tests for v43 OI ticker parsing and ring buffer."""

from __future__ import annotations

import pytest

from agent.core.v43_oi_frames import (
    _parse_oi_ticker,
    clear_oi_ring_buffer,
    export_oi_ring_buffer,
    load_oi_ring_buffer_from_records,
)


def test_parse_oi_ticker_delta_shape() -> None:
    resp = {
        "success": True,
        "result": {
            "symbol": "BTCUSD",
            "oi": "12500",
            "oi_value_usd": "850000",
            "taker_buy_vol": 100,
            "taker_sell_vol": 100,
            "mark_price": "67000",
            "spot_price": "66980",
            "quotes": {
                "best_bid": "66995",
                "best_ask": "67005",
                "bid_size": "120",
                "ask_size": "85",
            },
            "price_band": {"upper_limit": "68650", "lower_limit": "65350"},
            "predicted_funding_rate": "0.00012",
        },
    }
    parsed = _parse_oi_ticker(resp)
    assert parsed["oi_contracts"] == 12500.0
    assert parsed["oi_value_usd"] == 850000.0
    assert parsed["taker_buy_ratio"] == pytest.approx(0.5)
    assert parsed["mark_price"] == 67000.0
    assert parsed["spot_price"] == 66980.0
    assert parsed["bid_size"] == 120.0
    assert parsed["ask_size"] == 85.0
    assert parsed["price_band_upper"] == 68650.0
    assert parsed["predicted_funding_rate"] == pytest.approx(0.00012)


def test_parse_oi_ticker_malformed_returns_zeros() -> None:
    assert _parse_oi_ticker(None)["oi_contracts"] == 0.0
    assert _parse_oi_ticker({})["oi_contracts"] == 0.0


def test_oi_ring_buffer_load_export() -> None:
    clear_oi_ring_buffer()
    n = load_oi_ring_buffer_from_records(
        "BTCUSD",
        [
            {"timestamp": 1700000000, "oi_contracts": 100.0, "oi_value_usd": 1e6},
            {"timestamp": 1700000300, "oi_contracts": 101.0, "oi_value_usd": 1.01e6},
        ],
    )
    assert n == 2
    exported = export_oi_ring_buffer("BTCUSD")
    assert len(exported) == 2
    assert exported[0]["oi_contracts"] == 100.0
    clear_oi_ring_buffer("BTCUSD")
