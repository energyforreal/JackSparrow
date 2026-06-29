"""Unit tests for Trade Lifecycle Engine."""

from unittest.mock import MagicMock

import pytest

from agent.core.trade_lifecycle_engine import evaluate_lifecycle


def _position(**kwargs) -> dict:
    base = {
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 100.0,
        "current_price": 102.0,
        "stop_loss": 98.0,
        "take_profit": 105.0,
        "conviction_at_entry": 0.8,
    }
    base.update(kwargs)
    return base


def _snapshot() -> dict:
    return {
        "decision_context": {
            "features": {
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "ema_9": 101.0,
                "ema_21": 100.0,
                "atr_14": 2.0,
            },
            "gate_evaluation": {"categories": {"trend": True, "structure": True}},
        }
    }


def _live_mc(**kwargs) -> dict:
    base = {
        "symbol": "BTCUSD",
        "regime": "trending",
        "policy_verdict": {"conviction": 0.85, "signal": "HOLD"},
        "features": {
            "adx_14": 30.0,
            "rsi_14": 58.0,
            "ema_9": 102.0,
            "ema_21": 100.5,
            "atr_14": 2.5,
        },
        "rule_based_pipeline": {
            "fsm_decision": {"thesis_health": "healthy", "exit_signal": False},
            "structural_gates": {"categories": {"trend": True}},
        },
    }
    base.update(kwargs)
    return base


@pytest.fixture
def mock_settings(monkeypatch):
    s = MagicMock()
    s.trade_lifecycle_health_hold_min = 70.0
    s.trade_lifecycle_health_tighten_min = 50.0
    s.trade_lifecycle_health_exit_max = 50.0
    s.trade_lifecycle_conviction_exit_delta = -0.25
    s.trade_lifecycle_flip_exit_score = 0.70
    s.trade_lifecycle_fsm_broken_exit = True
    s.trade_lifecycle_tighten_lock_fraction = 0.5
    s.trade_lifecycle_opportunity_extend_min = 80.0
    s.trade_lifecycle_opportunity_reduce_min = 40.0
    s.trade_lifecycle_conviction_extend_delta = 0.10
    s.trade_lifecycle_tp_recompute_use_live_atr = True
    s.trade_lifecycle_tp_modify_min_interval_seconds = 0
    s.trade_lifecycle_tp_modify_min_change_pct = 0.001
    s.flip_score_threshold_low = 0.55
    s.position_exit_ml_confidence_min = 0.70
    s.jacksparrow_v43_short_execution_enabled = False
    s.stop_loss_percentage = 0.01
    s.take_profit_percentage = 0.02
    s.use_atr_scaled_sl_tp = True
    s.atr_sl_distance_mult = 1.0
    s.atr_tp_distance_mult = 1.5
    monkeypatch.setattr("agent.core.trade_lifecycle_engine.settings", s)
    return s


def test_lifecycle_hold_healthy(mock_settings) -> None:
    verdict = evaluate_lifecycle(_position(), _snapshot(), _live_mc())
    assert verdict.action == "HOLD"
    assert verdict.health_score >= 70.0


def test_lifecycle_exit_opposite_signal(mock_settings) -> None:
    mc = _live_mc(policy_verdict={"conviction": 0.5, "signal": "SELL"}, signal="SELL")
    verdict = evaluate_lifecycle(_position(), _snapshot(), mc)
    assert verdict.action == "EXIT"
    assert "opposite" in verdict.exit_reason_detail or verdict.health_score < 50


def test_lifecycle_exit_broken_thesis(mock_settings) -> None:
    mc = _live_mc(
        features={"adx_14": 15.0, "rsi_14": 40.0, "ema_9": 98.0, "ema_21": 100.0, "atr_14": 2.0},
        rule_based_pipeline={
            "fsm_decision": {"thesis_health": "broken", "exit_signal": True},
        },
    )
    verdict = evaluate_lifecycle(_position(), _snapshot(), mc)
    assert verdict.action == "EXIT"


def test_lifecycle_modify_tp_extend(mock_settings) -> None:
    mc = _live_mc(
        policy_verdict={"conviction": 0.95, "signal": "HOLD"},
        features={
            "adx_14": 35.0,
            "rsi_14": 62.0,
            "ema_9": 104.0,
            "ema_21": 101.0,
            "atr_14": 3.0,
        },
    )
    verdict = evaluate_lifecycle(
        _position(current_price=104.0, take_profit=105.0),
        _snapshot(),
        mc,
    )
    assert verdict.action in ("MODIFY_TP", "HOLD", "TIGHTEN_SL")
    if verdict.action == "MODIFY_TP":
        assert verdict.tp_direction == "extend"
        assert verdict.new_take_profit is not None
        assert verdict.new_take_profit > 105.0
