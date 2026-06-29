"""Unit tests for continuation thesis evaluation."""

from agent.core.continuation_thesis import evaluate_continuation


def _entry_snapshot(
    *,
    adx: float = 28.0,
    rsi: float = 55.0,
    ema9: float = 101.0,
    ema21: float = 100.0,
    trend_gate: bool = True,
) -> dict:
    return {
        "decision_context": {
            "features": {
                "adx_14": adx,
                "rsi_14": rsi,
                "ema_9": ema9,
                "ema_21": ema21,
            },
            "gate_evaluation": {
                "categories": {"trend": trend_gate, "structure": True},
            },
        }
    }


def test_continuation_healthy_long_aligned() -> None:
    live_mc = {
        "features": {"adx_14": 30.0, "rsi_14": 58.0, "ema_9": 102.0, "ema_21": 100.5},
        "regime": "trending",
        "rule_based_pipeline": {
            "fsm_decision": {"thesis_health": "healthy"},
            "structural_gates": {"categories": {"trend": True, "structure": True}},
        },
    }
    result = evaluate_continuation(
        {"side": "long"},
        _entry_snapshot(),
        live_mc,
    )
    assert result.alignment >= 0.9
    assert result.would_enter_same_side_now is True
    assert not result.invalidation_codes


def test_continuation_ema_death_cross_invalidates_long() -> None:
    live_mc = {
        "features": {"adx_14": 28.0, "rsi_14": 55.0, "ema_9": 99.0, "ema_21": 100.0},
        "rule_based_pipeline": {"fsm_decision": {"thesis_health": "weakening"}},
    }
    result = evaluate_continuation(
        {"side": "long"},
        _entry_snapshot(ema9=101.0, ema21=100.0),
        live_mc,
    )
    assert "ema_death_cross" in result.invalidation_codes
    assert result.alignment < 0.85
    assert result.would_enter_same_side_now is False


def test_continuation_fsm_broken_low_alignment() -> None:
    live_mc = {
        "features": {"adx_14": 15.0, "rsi_14": 42.0, "ema_9": 99.0, "ema_21": 100.0},
        "rule_based_pipeline": {"fsm_decision": {"thesis_health": "broken"}},
    }
    result = evaluate_continuation({"side": "long"}, _entry_snapshot(), live_mc)
    assert "fsm_thesis_broken" in result.invalidation_codes
    assert result.alignment < 0.6
