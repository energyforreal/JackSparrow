"""TP ratchet invariant tests for Trade Lifecycle Engine."""

from unittest.mock import MagicMock

import pytest

from agent.core.trade_lifecycle_engine import evaluate_lifecycle


@pytest.fixture
def mock_settings(monkeypatch):
    s = MagicMock()
    for key, val in (
        ("trade_lifecycle_health_hold_min", 70.0),
        ("trade_lifecycle_health_tighten_min", 50.0),
        ("trade_lifecycle_health_exit_max", 50.0),
        ("trade_lifecycle_conviction_exit_delta", -0.25),
        ("trade_lifecycle_flip_exit_score", 0.70),
        ("trade_lifecycle_fsm_broken_exit", True),
        ("trade_lifecycle_tighten_lock_fraction", 0.5),
        ("trade_lifecycle_opportunity_extend_min", 80.0),
        ("trade_lifecycle_opportunity_reduce_min", 40.0),
        ("trade_lifecycle_conviction_extend_delta", 0.10),
        ("trade_lifecycle_tp_recompute_use_live_atr", True),
        ("trade_lifecycle_tp_modify_min_interval_seconds", 0),
        ("trade_lifecycle_tp_modify_min_change_pct", 0.001),
        ("flip_score_threshold_low", 0.55),
        ("position_exit_ml_confidence_min", 0.70),
        ("jacksparrow_v43_short_execution_enabled", False),
        ("stop_loss_percentage", 0.01),
        ("take_profit_percentage", 0.02),
        ("use_atr_scaled_sl_tp", True),
        ("atr_sl_distance_mult", 1.0),
        ("atr_tp_distance_mult", 1.5),
    ):
        setattr(s, key, val)
    monkeypatch.setattr("agent.core.trade_lifecycle_engine.settings", s)
    return s


def test_extend_only_increases_tp_long(mock_settings) -> None:
    position = {
        "side": "long",
        "entry_price": 100.0,
        "current_price": 104.0,
        "stop_loss": 98.0,
        "take_profit": 105.0,
        "conviction_at_entry": 0.75,
    }
    live_mc = {
        "regime": "trending",
        "policy_verdict": {"conviction": 0.90, "signal": "HOLD"},
        "features": {
            "adx_14": 35.0,
            "rsi_14": 62.0,
            "ema_9": 104.0,
            "ema_21": 101.0,
            "atr_14": 4.0,
        },
        "rule_based_pipeline": {
            "fsm_decision": {"thesis_health": "healthy"},
            "structural_gates": {"categories": {"trend": True}},
        },
    }
    snapshot = {
        "decision_context": {
            "features": {
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "ema_9": 101.0,
                "ema_21": 100.0,
                "atr_14": 2.0,
            },
            "gate_evaluation": {"categories": {"trend": True}},
        }
    }
    verdict = evaluate_lifecycle(position, snapshot, live_mc)
    if verdict.action == "MODIFY_TP" and verdict.tp_direction == "extend":
        assert verdict.new_take_profit is not None
        assert verdict.new_take_profit > 105.0
