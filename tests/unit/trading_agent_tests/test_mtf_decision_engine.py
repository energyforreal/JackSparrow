"""Tests for MTF decision synthesis."""

from types import SimpleNamespace

import pytest

from agent.core.mtf_decision_engine import (
    index_predictions_by_timeframe,
    parse_timeframe_from_model_name,
    synthesize_mtf_trading_decision,
)


def test_parse_timeframe_from_model_name():
    assert parse_timeframe_from_model_name("jacksparrow_BTCUSD_15m") == "15m"
    assert parse_timeframe_from_model_name("foo_1h") == "1h"
    assert parse_timeframe_from_model_name("no_suffix") is None


def _pred(name: str, sig: float, conf: float) -> dict:
    return {
        "model_name": name,
        "prediction": sig,
        "confidence": conf,
        "context": {"entry_signal": sig, "entry_confidence": conf},
    }


def test_index_predictions_by_timeframe():
    preds = [_pred("m_BTC_5m", 0.3, 0.7), _pred("m_BTC_15m", 0.25, 0.65)]
    by_tf = index_predictions_by_timeframe(preds)
    assert "5m" in by_tf and "15m" in by_tf
    assert by_tf["5m"]["signal"] == pytest.approx(0.3)


def test_synthesize_mtf_bullish_buy():
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_trend_timeframe="15m",
        mtf_entry_timeframe="5m",
        mtf_filter_timeframe="none",
        mtf_trend_fallback_timeframes="",
        mtf_entry_fallback_timeframes="",
        mtf_entry_min_confidence=0.6,
        mtf_trend_signal_threshold=0.1,
        mtf_entry_signal_threshold=0.15,
    )
    preds = [
        _pred("jack_BTC_15m", 0.2, 0.7),
        _pred("jack_BTC_5m", 0.25, 0.65),
    ]
    code, _, conf, _ = synthesize_mtf_trading_decision(preds, settings)
    assert code == "BUY"
    assert conf == pytest.approx(0.65)


def test_synthesize_disabled_returns_none():
    settings = SimpleNamespace(mtf_decision_engine_enabled=False)
    assert synthesize_mtf_trading_decision([_pred("x_15m", 1, 1)], settings) is None


def test_synthesize_neutral_trend_hold():
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_trend_timeframe="15m",
        mtf_entry_timeframe="5m",
        mtf_filter_timeframe="none",
        mtf_trend_fallback_timeframes="",
        mtf_entry_fallback_timeframes="",
        mtf_entry_min_confidence=0.6,
        mtf_trend_signal_threshold=0.1,
        mtf_entry_signal_threshold=0.15,
    )
    preds = [
        _pred("jack_BTC_15m", 0.05, 0.7),
        _pred("jack_BTC_5m", 0.5, 0.9),
    ]
    code, conclusion, _, _ = synthesize_mtf_trading_decision(preds, settings)
    assert code == "HOLD"
    assert "neutral" in conclusion.lower()
