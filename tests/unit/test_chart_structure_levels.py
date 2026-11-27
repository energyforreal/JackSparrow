"""Structure price export and chart zone assembly for Market Analysis."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import NATIVE_STRUCTURE_COLS
from feature_store.transformer_btcusd.structure import (
    _SR_DELTA_ATR,
    add_market_structure_features,
)
from research.swinging.decision_contract import build_algorithmic_decision
from research.swinging.mtf_score import (
    chart_structure_levels,
    collect_active_patterns,
    structure_zone,
)
from tests.unit.swinging_fixtures import make_ohlcv


def test_structure_persists_support_resistance_prices_off_contract() -> None:
    frame = make_ohlcv(120, freq="1h", drift=0.5)
    feat = add_market_structure_features(frame)
    assert "support_price" in feat.columns
    assert "resistance_price" in feat.columns
    assert "support_price" not in NATIVE_STRUCTURE_COLS
    assert "resistance_price" not in NATIVE_STRUCTURE_COLS
    assert "dist_to_support_atr" in feat.columns
    last = feat.iloc[-1]
    assert np.isfinite(last["support_price"])
    assert np.isfinite(last["resistance_price"])
    # On breakouts, Donchian fallback can sit inside the current bar —
    # only require finite positive prices and unchanged distance columns.
    assert float(last["support_price"]) > 0.0
    assert float(last["resistance_price"]) > 0.0
    assert np.isfinite(last["dist_to_support_atr"])
    assert np.isfinite(last["dist_to_resistance_atr"])


def test_structure_zone_half_width_is_half_atr() -> None:
    row = {
        "support_price": 100.0,
        "resistance_price": 110.0,
        "atr_14": 4.0,
    }
    support = structure_zone(row, timeframe="1h", kind="support")
    resistance = structure_zone(row, timeframe="4h", kind="resistance")
    assert support is not None
    assert resistance is not None
    half = _SR_DELTA_ATR * 4.0
    assert support["price"] == 100.0
    assert support["low"] == pytest.approx(100.0 - half)
    assert support["high"] == pytest.approx(100.0 + half)
    assert support["timeframe"] == "1h"
    assert resistance["timeframe"] == "4h"
    assert resistance["low"] == pytest.approx(110.0 - half)


def test_chart_structure_levels_from_1h_and_4h_rows() -> None:
    rows = {
        "1h": {"support_price": 90.0, "resistance_price": 105.0, "atr_14": 2.0},
        "4h": {"support_price": 85.0, "resistance_price": 120.0, "atr_14": 5.0},
        "5m": {"close": 100.0},
    }
    levels = chart_structure_levels(rows)
    assert len(levels["support_zones"]) == 2
    assert len(levels["resistance_zones"]) == 2
    assert {z["timeframe"] for z in levels["support_zones"]} == {"1h", "4h"}


def test_build_algorithmic_decision_copies_zones_and_clears_hold_brackets() -> None:
    zones = [
        {"timeframe": "1h", "price": 95.0, "low": 94.0, "high": 96.0},
        {"timeframe": "4h", "price": 90.0, "low": 88.0, "high": 92.0},
    ]
    held = build_algorithmic_decision(
        symbol="BTCUSD",
        scored={
            "signal": "HOLD",
            "confidence": 0.4,
            "score": 40.0,
            "decision_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "entry_price": 100.0,
            "close": 100.0,
            "stop_price": 90.0,
            "take_profit_price": 120.0,
            "support_zones": zones,
            "resistance_zones": [
                {"timeframe": "1h", "price": 110.0, "low": 109.0, "high": 111.0}
            ],
            "active_patterns": [
                {
                    "time": 1_700_000_000,
                    "name": "cdl_hammer",
                    "label": "Hammer",
                    "direction": "bullish",
                    "timeframe": "5m",
                    "kind": "candlestick",
                    "price": 99.5,
                }
            ],
            "invalidation": "below_threshold",
            "long_score": 40.0,
            "short_score": 10.0,
            "components": {},
        },
        reasons=[],
        decision_id="hold-1",
    )
    assert held["entry"] is None
    assert held["risk"]["stop_loss"] is None
    assert held["risk"]["take_profit"] is None
    assert held["valid"] is False
    assert held["support_zones"][0]["price"] == 95.0
    assert held["resistance_zones"][0]["timeframe"] == "1h"
    assert held["active_patterns"][0]["name"] == "cdl_hammer"

    buy = build_algorithmic_decision(
        symbol="BTCUSD",
        scored={
            "signal": "BUY",
            "confidence": 0.78,
            "score": 78.0,
            "decision_time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "entry_price": 100.0,
            "close": 100.0,
            "stop_price": 94.0,
            "take_profit_price": 110.0,
            "support_zones": zones,
            "resistance_zones": [],
            "active_patterns": [],
            "invalidation": "",
            "long_score": 78.0,
            "short_score": 10.0,
            "long_components": {"trend_4h": 20.0},
            "components": {"trend_4h": 20.0},
        },
        reasons=["algorithmic_qualified"],
        decision_id="buy-1",
    )
    assert buy["entry"] == 100.0
    assert buy["risk"]["stop_loss"] == 94.0
    assert buy["risk"]["take_profit"] == 110.0
    assert buy["valid"] is True
    assert buy["risk_reward"] == pytest.approx(10.0 / 6.0)
    assert buy["active_patterns"] == []


def test_collect_active_patterns_from_prepared_frames() -> None:
    decision_time = pd.Timestamp("2024-01-01 01:00:00", tz="UTC")
    five = pd.DataFrame(
        [
            {
                "time": pd.Timestamp("2024-01-01 00:50:00", tz="UTC"),
                "close": 100.0,
                "cdl_hammer": 1.0,
                "cdl_bull_engulfing": 0.0,
                "cdl_inv_hammer": 0.0,
                "cdl_morning_star": 0.0,
                "cdl_bear_engulfing": 0.0,
                "cdl_shooting_star": 0.0,
                "cdl_hanging_man": 0.0,
                "cdl_evening_star": 0.0,
            },
            {
                "time": pd.Timestamp("2024-01-01 00:55:00", tz="UTC"),
                "close": 101.0,
                "cdl_hammer": 0.0,
                "cdl_bull_engulfing": 0.0,
                "cdl_inv_hammer": 0.0,
                "cdl_morning_star": 0.0,
                "cdl_bear_engulfing": 0.0,
                "cdl_shooting_star": 1.0,
                "cdl_hanging_man": 0.0,
                "cdl_evening_star": 0.0,
            },
        ]
    )
    fifteen = pd.DataFrame(
        [
            {
                "time": pd.Timestamp("2024-01-01 00:30:00", tz="UTC"),
                "close": 100.5,
                "chp_bull_flag": 1.0,
                "chp_asc_triangle": 0.0,
                "chp_double_bottom": 0.0,
                "chp_ihs_detected": 0.0,
                "tl_breakout_up": 0.0,
                "chp_bear_flag": 0.0,
                "chp_desc_triangle": 0.0,
                "chp_double_top": 0.0,
                "chp_hs_detected": 0.0,
                "tl_breakout_down": 0.0,
            }
        ]
    )
    hits = collect_active_patterns(
        {"5m": five, "15m": fifteen},
        decision_time=decision_time,
    )
    names = {item["name"] for item in hits}
    assert "cdl_hammer" in names
    assert "cdl_shooting_star" in names
    assert "chp_bull_flag" in names
    hammer = next(item for item in hits if item["name"] == "cdl_hammer")
    assert hammer["kind"] == "candlestick"
    assert hammer["direction"] == "bullish"
    flag = next(item for item in hits if item["name"] == "chp_bull_flag")
    assert flag["kind"] == "chart"
    assert flag["label"] == "Bull Flag"
