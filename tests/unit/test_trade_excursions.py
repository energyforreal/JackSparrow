"""Unit tests for trade excursion computation."""

from __future__ import annotations

from agent.persistence.trade_excursions import compute_excursions, price_delta_excursions


def test_compute_excursions_long():
    candles = [
        {"high": 101.0, "low": 99.0, "close": 100.0},
        {"high": 103.0, "low": 100.0, "close": 102.0},
    ]
    exc = compute_excursions(
        side="long",
        entry_price=100.0,
        candles=candles,
        sl=98.0,
        tp=105.0,
    )
    assert exc["mfe_usd"] == 3.0
    assert exc["mfe_pct"] > 0
    assert exc["mode"] == "candle_replay"


def test_price_delta_excursions():
    exc = price_delta_excursions(side="long", entry_price=100.0, exit_price=102.0)
    assert exc["mfe_usd"] == 2.0
    assert exc["mode"] == "price_delta_only"
