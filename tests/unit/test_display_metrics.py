"""Tests for display-only dashboard metrics."""

from __future__ import annotations

from agent.core.display_metrics import build_display_metrics


def test_build_display_metrics_economic_edge_long() -> None:
    out = build_display_metrics(
        signal="LONG",
        policy_confidence=0.65,
        market_context={
            "ml_validation": {
                "expected_return": 0.012,
                "threshold": 0.005,
            }
        },
        reasoning_chain={
            "final_confidence": 0.68,
            "reasoning_confidence_raw": 0.55,
            "entry_proba_margin_mean": 0.22,
        },
        payload={
            "trade_score_detail": {
                "score": 72.0,
                "passed": True,
                "components": {"thesis": 25.0, "ml": 15.0},
                "reason_codes": ["score_thesis_active"],
            }
        },
    )
    assert out["economic_edge"] == 0.007
    assert out["entry_proba_margin"] == 0.22
    assert out["reasoning_confidence_raw"] == 0.55
    assert out["trade_score_detail"]["score"] == 72.0
    hint = out["metric_correlation_hint"]
    assert hint is not None
    assert abs(hint["policy_reasoning_delta"] - 0.03) < 1e-6


def test_build_display_metrics_trade_score_from_market_context() -> None:
    out = build_display_metrics(
        signal="HOLD",
        policy_confidence=0.5,
        market_context={
            "trade_score": {
                "score": 40.0,
                "passed": False,
                "components": {"structure": 10.0},
                "reason_codes": [],
            }
        },
    )
    assert out["trade_score_detail"]["score"] == 40.0
