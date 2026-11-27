"""Chart payload assembly from candles + cached trading decisions."""

from __future__ import annotations

import pytest

from backend.services.chart_service import (
    assemble_chart_payload,
    normalize_candles,
    trade_plan_from_decision,
)


def test_normalize_candles_uses_unix_seconds() -> None:
    candles, volume = normalize_candles(
        [
            {
                "timestamp": 1_700_000_000,
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
            },
            {
                "time": 1_700_000_300_000,  # ms
                "open": 1.5,
                "high": 2.5,
                "low": 1.4,
                "close": 2.0,
                "volume": 12,
            },
        ]
    )
    assert candles[0]["time"] == 1_700_000_000
    assert candles[1]["time"] == 1_700_000_300
    assert volume[1]["value"] == 12.0


def test_assemble_chart_merges_decision_zones_and_plan() -> None:
    market = {
        "candles": [
            {
                "timestamp": 1_700_000_000,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 5,
            }
        ],
        "current_price": 100.7,
    }
    signal = {
        "trading_decision": {
            "decision_id": "d1",
            "decision_path": "algorithmic",
            "signal": "BUY",
            "score": 78.0,
            "entry": 100.5,
            "candle_timestamp": "2024-01-01T00:05:00+00:00",
            "risk": {"stop_loss": 98.0, "take_profit": 104.0},
            "support_zones": [
                {"timeframe": "1h", "price": 97.0, "low": 96.5, "high": 97.5}
            ],
            "resistance_zones": [
                {"timeframe": "4h", "price": 110.0, "low": 109.0, "high": 111.0}
            ],
            "active_patterns": [
                {
                    "time": 1_700_000_000,
                    "name": "cdl_hammer",
                    "label": "Hammer",
                    "direction": "bullish",
                    "timeframe": "5m",
                    "kind": "candlestick",
                    "price": 100.2,
                }
            ],
            "valid": True,
            "invalidation": [],
        }
    }
    payload = assemble_chart_payload(
        symbol="BTCUSD",
        timeframe="15m",
        market_data=market,
        signal_snapshot=signal,
    )
    assert payload["symbol"] == "BTCUSD"
    assert payload["timeframe"] == "15m"
    assert len(payload["candles"]) == 1
    assert payload["current_price"] == 100.7
    assert payload["support_zones"][0]["timeframe"] == "1h"
    assert payload["resistance_zones"][0]["price"] == 110.0
    assert payload["active_patterns"][0]["label"] == "Hammer"
    assert payload["active_patterns"][0]["kind"] == "candlestick"
    assert payload["trade_plan"]["signal"] == "BUY"
    assert payload["trade_plan"]["entry"] == 100.5
    assert payload["trade_plan"]["stop_loss"] == 98.0
    assert payload["trade_plan"]["take_profit"] == 104.0
    assert payload["trade_plan"]["valid"] is True
    assert payload["trade_plan"]["risk_reward"] == pytest.approx(
        abs(104.0 - 100.5) / abs(100.5 - 98.0)
    )


def test_assemble_chart_empty_zones_when_cache_has_none() -> None:
    market = {
        "candles": [
            {
                "timestamp": 1_700_000_000,
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 1,
            }
        ]
    }
    signal = {
        "trading_decision": {
            "signal": "HOLD",
            "score": 20.0,
            "risk": {"stop_loss": 1.0, "take_profit": 2.0},
            "invalidation": ["below_threshold"],
        }
    }
    payload = assemble_chart_payload(
        symbol="BTCUSD",
        timeframe="15m",
        market_data=market,
        signal_snapshot=signal,
    )
    assert payload["support_zones"] == []
    assert payload["resistance_zones"] == []
    assert payload["active_patterns"] == []
    assert payload["trade_plan"]["entry"] is None
    assert payload["trade_plan"]["stop_loss"] is None
    assert payload["trade_plan"]["take_profit"] is None
    assert payload["trade_plan"]["valid"] is False


def test_trade_plan_from_decision_hold_clears_brackets() -> None:
    plan = trade_plan_from_decision(
        {
            "signal": "HOLD",
            "entry": 100.0,
            "risk": {"stop_loss": 90.0, "take_profit": 120.0},
            "score": 40.0,
            "invalidation": ["below_threshold"],
        }
    )
    assert plan["entry"] is None
    assert plan["stop_loss"] is None
    assert plan["take_profit"] is None
    assert plan["valid"] is False

