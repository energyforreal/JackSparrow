"""Unit tests for deterministic post-trade reflection engine."""

from __future__ import annotations

from agent.core.agent_reflection_engine import REFLECTION_VERSION, reflect_on_trade


def test_reflect_long_profitable_aligned() -> None:
    snap = reflect_on_trade(
        symbol="BTCUSD",
        position_id="pos_1",
        predicted_signal="BUY",
        pnl=120.5,
        exit_reason="take_profit",
        confidence_at_entry=0.8,
    )
    d = snap.to_dict()
    assert d["version"] == REFLECTION_VERSION
    assert d["advisory_only"] is True
    assert d["was_profitable"] is True
    assert d["direction_correct"] is True
    assert "direction_aligned_with_pnl" in d["reason_codes"]
    assert d["quality_score"] >= 0.5


def test_reflect_short_loss_misaligned() -> None:
    snap = reflect_on_trade(
        symbol="BTCUSD",
        position_id="pos_2",
        predicted_signal="SELL",
        pnl=-50.0,
        exit_reason="stop_loss",
        confidence_at_entry=0.85,
        introspection_at_entry={"trade_score_pass": False, "v43_gate_reject": "debounce"},
    )
    d = snap.to_dict()
    assert d["direction_correct"] is False
    assert "direction_misaligned_with_pnl" in d["reason_codes"]
    assert "entry_below_trade_score_min" in d["reason_codes"]
    assert "high_confidence_loss" in d["reason_codes"]
