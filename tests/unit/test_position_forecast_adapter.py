"""Unit tests for position forecast adapter."""

import pytest

from agent.core.position_forecast_adapter import evaluate_forecast_adjustment


def test_forecast_exit_when_opposes_long() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {"decision_context": {"expectation": {"dominant_expectation": "bullish", "confidence": 0.7}}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "bearish", "confidence": 0.72}
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    assert adj.hint == "exit_candidate"
    assert "forecast_opposes_position" in adj.reason_codes


def test_forecast_extend_when_aligned_upgrade() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {"decision_context": {"expectation": {"dominant_expectation": "bullish", "confidence": 0.55}}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "bullish", "confidence": 0.68}
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    assert adj.hint == "extend_tp"


# --- Regression tests using the *real* expectation_engine vocabulary --------------
# expectation_engine.evaluate_expectation() only ever emits dominant_expectation in
# {"trend_continuation", "breakout", "reversal", "vol_expansion", "neutral"} — never
# "bullish"/"bearish". These labels are directionless; they must be combined with
# understanding.direction_bias to determine alignment with an open position.


def test_trend_continuation_aligned_with_long_when_bias_long() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {
        "decision_context": {
            "decision_context_v3": {
                "expectation": {"dominant_expectation": "trend_continuation", "confidence": 0.5},
                "understanding": {"direction_bias": "LONG"},
            }
        }
    }
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "trend_continuation", "confidence": 0.7},
            "understanding": {"direction_bias": "LONG"},
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    # Aligned (long position, bullish trend continuation) + confidence upgrade -> extend.
    assert adj.hint == "extend_tp"


def test_reversal_dominant_triggers_exit_for_long_in_uptrend() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {"decision_context": {}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "reversal", "confidence": 0.6},
            "understanding": {"direction_bias": "LONG"},
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    # Reversal risk while direction_bias is LONG threatens a long position -> exit candidate.
    assert adj.hint == "exit_candidate"
    assert "forecast_opposes_position" in adj.reason_codes


def test_reversal_dominant_does_not_threaten_short_in_uptrend() -> None:
    # A reversal away from an uptrend favors shorts, not longs -- so a short position
    # should NOT be flagged as opposed here.
    position = {"side": "short", "symbol": "BTCUSD"}
    entry = {"decision_context": {}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "reversal", "confidence": 0.6},
            "understanding": {"direction_bias": "LONG"},
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    assert adj.hint != "exit_candidate"


def test_vol_expansion_is_directionally_ambiguous_and_does_not_force_exit() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {"decision_context": {}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "vol_expansion", "confidence": 0.9},
            "understanding": {"direction_bias": "LONG"},
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    # vol_expansion carries no directional read -- must never be treated as opposing.
    assert adj.hint != "exit_candidate"


def test_entry_expectation_reads_nested_decision_context_v3() -> None:
    # Regression: real trade_snapshot.py nests expectation under
    # decision_context["decision_context_v3"]["expectation"], not decision_context["expectation"].
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {
        "decision_context": {
            "decision_context_v3": {
                "expectation": {"dominant_expectation": "trend_continuation", "confidence": 0.5},
                "understanding": {"direction_bias": "LONG"},
            }
        }
    }
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "trend_continuation", "confidence": 0.3},
            "understanding": {"direction_bias": "LONG"},
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    # Confidence dropped 0.5 -> 0.3 (delta -0.2): entry data must actually be read for
    # this delta to be computed at all -- prior to the fix entry_conf silently defaulted
    # to live conf, making conf_delta always 0.0 for real (nested) snapshots.
    assert adj.confidence_delta == pytest.approx(-0.2, abs=1e-9)
