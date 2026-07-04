"""Unit tests for post-entry position intelligence."""

from agent.core.continuation_thesis import ContinuationResult
from agent.core.position_intelligence import evaluate_position_quality


def test_evaluate_position_quality_scores_health_and_opportunity() -> None:
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 60000.0,
        "current_price": 60500.0,
        "conviction_at_entry": 0.7,
    }
    entry_snapshot = {
        "signal": "LONG",
        "conviction": 0.7,
        "thesis_type": "breakout",
    }
    live_mc = {
        "symbol": "BTCUSD",
        "regime": "trending",
        "conviction": 0.72,
        "market_structure": {"regime": "trending", "market_type": "TRENDING"},
        "ml_validation": {
            "final_long": True,
            "final_short": False,
            "expected_return": 0.01,
            "threshold": 0.005,
        },
    }
    quality = evaluate_position_quality(position, entry_snapshot, live_mc)
    assert 0.0 <= quality.health_score <= 100.0
    assert 0.0 <= quality.opportunity_score <= 100.0
    assert quality.continuation.alignment >= 0.0
    assert quality.thesis_valid is True


def test_position_quality_opposite_signal() -> None:
    position = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 60000.0,
        "current_price": 59800.0,
        "conviction_at_entry": 0.65,
    }
    live_mc = {
        "symbol": "BTCUSD",
        "decision": {"signal": "SHORT"},
        "ml_validation": {
            "final_long": False,
            "final_short": True,
            "expected_return": -0.02,
            "threshold": 0.005,
            "short_threshold": 0.005,
        },
    }
    quality = evaluate_position_quality(position, {}, live_mc)
    assert isinstance(quality.continuation, ContinuationResult)
