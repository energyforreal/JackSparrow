"""Rollout summary diff tests."""

from __future__ import annotations

from agent.testing.cognition_rollout import (
    BarDecisionRecord,
    RolloutSummary,
    build_summary_from_records,
    diff_summaries,
)


def test_diff_detects_policy_signal_change() -> None:
    base_records = [
        BarDecisionRecord(bar_id="strong_breakout", policy_signal="HOLD", trade_score=50.0),
    ]
    cur_records = [
        BarDecisionRecord(bar_id="strong_breakout", policy_signal="LONG", trade_score=55.0),
    ]
    baseline = build_summary_from_records(base_records, stage="phase0", symbol="BTCUSD")
    current = build_summary_from_records(cur_records, stage="stage1", symbol="BTCUSD")
    diff = diff_summaries(current, baseline)
    assert diff.signals_changed == 1
    assert diff.trade_score_mean_delta == 5.0
