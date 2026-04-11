"""Unit tests for Delta India paper model: margin, fees, liquidation threshold."""

import pytest

from agent.core.futures_utils import (
    margin_required_inr,
    net_pnl_usd_after_fees,
    net_pnl_usd_after_fees_split_legs,
    isolated_equity_usd,
)


def test_margin_required_inr_matches_notional_over_leverage():
    lots = 2
    price = 50_000.0
    usdinr = 83.0
    lev = 5
    cv = 0.001
    notional_usd = lots * price * cv
    margin_usd = notional_usd / lev
    expected_inr = margin_usd * usdinr
    got = margin_required_inr(lots, price, usdinr, lev, cv)
    assert got == pytest.approx(expected_inr)


def test_split_leg_fees_matches_round_trip_net():
    entry = 50_000.0
    exit_ = 51_000.0
    lots = 1.0
    cv = 0.001
    taker = 0.0005
    slip = 5.0
    g1, fees_rt, net_rt = net_pnl_usd_after_fees(
        entry, exit_, lots, "long", cv, taker, slip
    )
    g2, _fe, _fx, fees_tot, net_sp = net_pnl_usd_after_fees_split_legs(
        entry, exit_, lots, "long", cv, taker, slip
    )
    assert g1 == pytest.approx(g2)
    assert fees_rt == pytest.approx(fees_tot)
    assert net_rt == pytest.approx(net_sp)


def test_isolated_equity_liquidation_threshold():
    initial_margin_usd = 100.0
    upl = -51.0
    eq = isolated_equity_usd(initial_margin_usd, upl)
    maintenance = initial_margin_usd * 0.5
    assert eq < maintenance
