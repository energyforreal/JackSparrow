"""Replay calibration stubs for cognition layer."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context import DecisionContext
from agent.testing.cognition_replay import calibration_metrics_from_trace, counterfactual_strategy_scores


def test_counterfactual_from_decision_context() -> None:
    raw = {
        "meta": {"symbol": "BTCUSD", "bar_index": 100, "cycle_id": "t"},
        "understanding": {
            "symbol": "BTCUSD",
            "trend": "bullish",
            "trend_strength": "strong",
            "momentum": "increasing",
            "volatility": "stable",
            "direction_bias": "LONG",
        },
        "scenario": {"primary": "markup", "confidence": 0.75},
        "expectation": {
            "horizons": [
                {
                    "horizon_minutes": 30,
                    "trend_persistence": 0.8,
                    "breakout_likelihood": 0.4,
                    "reversal_risk": 0.2,
                    "volatility_expansion": 0.5,
                }
            ],
            "dominant_expectation": "trend_continuation",
            "confidence": 0.8,
        },
        "risk_intelligence": {"trade_environment_score": 0.7},
    }
    ctx = DecisionContext.from_dict(raw)
    report = counterfactual_strategy_scores(ctx, features={"adx_14": 30.0})
    assert "counterfactual_scores" in report
    assert len(report["counterfactual_scores"]) >= 5


def test_calibration_metrics_empty_layers() -> None:
    m = calibration_metrics_from_trace([])
    assert m["expectation_logged"] is False
