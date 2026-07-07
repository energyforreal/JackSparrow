"""Unit tests for position scale-out advisory stub."""

from agent.core.position_scale import evaluate_scale_out


def test_scale_out_on_opportunity_fade() -> None:
    decision = evaluate_scale_out(
        {"side": "long"},
        health_score=88.0,
        opportunity_score=40.0,
    )
    assert decision.action == "scale_out"
    assert decision.fraction == 0.5
