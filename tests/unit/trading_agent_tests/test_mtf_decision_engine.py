"""Tests for MTF decision synthesis."""

from types import SimpleNamespace

import pytest

from agent.core.entry_edge_tracker import EntryEdgeTracker
from agent.core.mtf_decision_engine import (
    compute_context_position_size_multiplier,
    index_predictions_by_timeframe,
    parse_timeframe_from_model_name,
    synthesize_mtf_trading_decision,
)


@pytest.fixture(autouse=True)
def _clear_edge_tracker():
    EntryEdgeTracker.clear_for_tests()
    yield
    EntryEdgeTracker.clear_for_tests()


def test_parse_timeframe_from_model_name():
    assert parse_timeframe_from_model_name("jacksparrow_BTCUSD_15m") == "15m"
    assert parse_timeframe_from_model_name("foo_1h") == "1h"
    assert parse_timeframe_from_model_name("no_suffix") is None


def _pred(name: str, sig: float, conf: float, proba: dict | None = None) -> dict:
    context = {"entry_signal": sig, "entry_confidence": conf}
    if proba is not None:
        context["entry_proba"] = proba
    return {
        "model_name": name,
        "prediction": sig,
        "confidence": conf,
        "context": context,
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


def test_synthesize_mtf_buy_with_entry_proba_gating():
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_trend_timeframe="15m",
        mtf_entry_timeframe="5m",
        mtf_filter_timeframe="none",
        mtf_trend_fallback_timeframes="",
        mtf_entry_fallback_timeframes="",
        mtf_entry_min_confidence=0.6,
        mtf_use_entry_proba_gating=True,
        mtf_trend_min_buy_prob=0.6,
        mtf_trend_min_sell_prob=0.6,
        mtf_entry_min_buy_prob=0.6,
        mtf_entry_min_sell_prob=0.6,
        mtf_strong_min_buy_prob=0.72,
        mtf_strong_min_sell_prob=0.72,
    )
    preds = [
        _pred("jack_BTC_15m", 0.1, 0.7, {"sell": 0.15, "hold": 0.2, "buy": 0.65}),
        _pred("jack_BTC_5m", 0.2, 0.66, {"sell": 0.14, "hold": 0.2, "buy": 0.66}),
    ]
    code, _, conf, _ = synthesize_mtf_trading_decision(preds, settings)
    assert code == "BUY"
    assert conf == pytest.approx(0.66)


def test_synthesize_mtf_proba_gating_blocks_low_entry_long_edge():
    """Prob-diff mode: small (buy-sell) on entry TF must not confirm a LONG."""
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_trend_timeframe="15m",
        mtf_entry_timeframe="5m",
        mtf_filter_timeframe="none",
        mtf_trend_fallback_timeframes="",
        mtf_entry_fallback_timeframes="",
        mtf_entry_min_confidence=0.6,
        mtf_use_entry_proba_gating=True,
        mtf_min_confidence_gap=0.0,
        mtf_trend_use_prob_diff=True,
        mtf_entry_use_prob_diff=True,
        mtf_entry_prob_diff_edge=0.08,
        mtf_trend_min_buy_prob=0.6,
        mtf_trend_min_sell_prob=0.6,
        mtf_entry_min_buy_prob=0.6,
        mtf_entry_min_sell_prob=0.6,
    )
    preds = [
        _pred("jack_BTC_15m", 0.1, 0.7, {"sell": 0.1, "hold": 0.2, "buy": 0.7}),
        _pred("jack_BTC_5m", 0.25, 0.7, {"sell": 0.46, "hold": 0.04, "buy": 0.50}),
    ]
    code, conclusion, _, _ = synthesize_mtf_trading_decision(preds, settings)
    assert code == "HOLD"
    assert "edge" in conclusion.lower()


def test_synthesize_mtf_proba_gap_hold_when_entry_uncertain():
    """|buy-sell| below mtf_min_confidence_gap should yield HOLD (JackSparrow v6-style filter)."""
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_trend_timeframe="15m",
        mtf_entry_timeframe="5m",
        mtf_filter_timeframe="none",
        mtf_trend_fallback_timeframes="",
        mtf_entry_fallback_timeframes="",
        mtf_entry_min_confidence=0.52,
        mtf_use_entry_proba_gating=True,
        mtf_trend_min_buy_prob=0.50,
        mtf_trend_min_sell_prob=0.50,
        mtf_entry_min_buy_prob=0.50,
        mtf_entry_min_sell_prob=0.50,
        mtf_min_confidence_gap=0.05,
    )
    preds = [
        _pred("jack_BTC_15m", 0.1, 0.7, {"sell": 0.2, "hold": 0.1, "buy": 0.7}),
        _pred("jack_BTC_5m", 0.2, 0.7, {"sell": 0.48, "hold": 0.04, "buy": 0.48}),
    ]
    code, conclusion, _, evidence = synthesize_mtf_trading_decision(preds, settings)
    assert code == "HOLD"
    assert "gap" in conclusion.lower()


def test_synthesize_mtf_percentile_blocks_when_history_stronger():
    """Rolling P80 gate rejects trades weaker than recent |buy-sell| history."""
    sym = "BTCUSD"
    for _ in range(40):
        EntryEdgeTracker.observe(sym, 0.22)
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_trend_timeframe="15m",
        mtf_entry_timeframe="5m",
        mtf_filter_timeframe="none",
        mtf_trend_fallback_timeframes="",
        mtf_entry_fallback_timeframes="",
        mtf_entry_min_confidence=0.5,
        mtf_use_entry_proba_gating=True,
        mtf_min_confidence_gap=0.0,
        mtf_trend_use_prob_diff=True,
        mtf_entry_use_prob_diff=True,
        mtf_entry_prob_diff_edge=0.08,
        mtf_entry_strength_percentile_enabled=True,
        mtf_entry_strength_percentile=80,
        mtf_entry_strength_percentile_min_samples=30,
    )
    preds = [
        _pred("jack_BTC_15m", 0.1, 0.7, {"sell": 0.15, "hold": 0.1, "buy": 0.75}),
        _pred("jack_BTC_5m", 0.2, 0.7, {"sell": 0.42, "hold": 0.03, "buy": 0.55}),
    ]
    code, conclusion, _, _ = synthesize_mtf_trading_decision(preds, settings, symbol=sym)
    assert code == "HOLD"
    assert "percentile" in conclusion.lower()


def test_short_tf_primary_long_and_strong():
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_signal_architecture="short_tf_primary",
        mtf_primary_signal_timeframe="5m",
        mtf_primary_signal_fallback_timeframes="",
        mtf_context_timeframe="15m",
        mtf_context_fallback_timeframes="",
        mtf_primary_dead_zone=0.05,
        mtf_primary_edge_long=0.08,
        mtf_primary_edge_short=0.08,
        mtf_primary_strong_long_min_prob=0.55,
        mtf_primary_strong_short_min_prob=0.58,
        mtf_entry_strength_percentile_enabled=False,
    )
    preds = [
        _pred("j_BTC_5m", 0.2, 0.6, {"sell": 0.30, "hold": 0.05, "buy": 0.65}),
        _pred("j_BTC_15m", 0.0, 0.5, {"sell": 0.40, "hold": 0.20, "buy": 0.40}),
    ]
    code, conclusion, conf, ev = synthesize_mtf_trading_decision(
        preds, settings, symbol="BTCUSD"
    )
    assert code == "STRONG_BUY"
    assert conf == pytest.approx(0.6)
    assert any("short-primary" in e for e in ev)


def test_short_tf_primary_dead_zone():
    settings = SimpleNamespace(
        mtf_decision_engine_enabled=True,
        mtf_signal_architecture="short_tf_primary",
        mtf_primary_signal_timeframe="5m",
        mtf_primary_signal_fallback_timeframes="",
        mtf_context_timeframe="15m",
        mtf_context_fallback_timeframes="",
        mtf_primary_dead_zone=0.05,
        mtf_primary_edge_long=0.08,
        mtf_primary_edge_short=0.08,
        mtf_primary_strong_long_min_prob=0.55,
        mtf_primary_strong_short_min_prob=0.58,
        mtf_entry_strength_percentile_enabled=False,
    )
    preds = [
        _pred("j_BTC_5m", 0.0, 0.5, {"sell": 0.48, "hold": 0.04, "buy": 0.52}),
    ]
    code, conclusion, _, _ = synthesize_mtf_trading_decision(preds, settings)
    assert code == "HOLD"
    assert "dead" in conclusion.lower()


def test_compute_context_multiplier_boost_when_aligned_long():
    settings = SimpleNamespace(
        mtf_signal_architecture="short_tf_primary",
        mtf_context_timeframe="15m",
        mtf_context_fallback_timeframes="",
        mtf_context_agree_edge=0.02,
        mtf_context_aligned_size_multiplier=1.15,
        mtf_context_misaligned_size_multiplier=0.75,
    )
    preds = [
        _pred("j_BTC_15m", 0.0, 0.5, {"sell": 0.30, "hold": 0.0, "buy": 0.70}),
    ]
    m = compute_context_position_size_multiplier("BUY", preds, settings)
    assert m == pytest.approx(1.15)


def test_compute_context_multiplier_standard_arch_is_one():
    settings = SimpleNamespace(mtf_signal_architecture="standard")
    preds = [_pred("j_BTC_15m", 0.0, 0.5, {"sell": 0.5, "hold": 0.0, "buy": 0.5})]
    assert compute_context_position_size_multiplier("BUY", preds, settings) == 1.0


def test_synthesize_mtf_proba_fallback_to_signal_thresholds():
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
        mtf_use_entry_proba_gating=True,
    )
    preds = [
        _pred("jack_BTC_15m", 0.22, 0.65),  # no entry_proba -> fallback branch
        _pred("jack_BTC_5m", 0.27, 0.66),
    ]
    code, _, _, evidence = synthesize_mtf_trading_decision(preds, settings)
    assert code == "BUY"
    assert any("fallback" in line.lower() for line in evidence)
