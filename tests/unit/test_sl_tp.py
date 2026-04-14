"""Unit tests for agent.core.sl_tp."""

import pytest

from agent.core.sl_tp import (
    compute_stop_take_prices,
    parse_risk_approved_side,
    rebase_sl_tp_to_fill,
)


def test_parse_risk_approved_side():
    assert parse_risk_approved_side("buy") == "BUY"
    assert parse_risk_approved_side("  sell ") == "SELL"
    assert parse_risk_approved_side("LONG") == "BUY"
    assert parse_risk_approved_side("SHORT") == "SELL"
    assert parse_risk_approved_side(None) == "BUY"
    assert parse_risk_approved_side("HOLD") is None


def test_compute_fixed_buy():
    sl, tp = compute_stop_take_prices(
        100_000.0,
        "BUY",
        0.01,
        0.02,
        tick_size=0.5,
    )
    assert sl == 99_000.0
    assert tp == 102_000.0


def test_compute_atr_wider_than_pct():
    # ATR branch: max(entry*pct, atr*mult)
    sl, tp = compute_stop_take_prices(
        100_000.0,
        "BUY",
        0.01,
        0.015,
        use_atr_scaled=True,
        atr_14=2_000.0,
        atr_sl_mult=1.0,
        atr_tp_mult=1.5,
        tick_size=0.5,
    )
    # sl_dist = max(1000, 2000) = 2000 -> SL 98000
    assert sl == 98_000.0
    # tp_dist = max(1500, 3000) = 3000 -> TP 103000
    assert tp == 103_000.0


def test_rebase_sl_tp_to_fill():
    sl, tp = rebase_sl_tp_to_fill(
        planned_entry=100_000.0,
        fill_price=100_050.0,
        stop_loss=99_000.0,
        take_profit=102_000.0,
        tick_size=0.5,
    )
    assert sl == 99_050.0
    assert tp == 102_050.0


def test_rebase_zero_delta():
    sl, tp = rebase_sl_tp_to_fill(100.0, 100.0, 99.0, 101.0, tick_size=None)
    assert sl == 99.0
    assert tp == 101.0
