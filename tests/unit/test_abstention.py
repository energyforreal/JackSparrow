"""Abstention taxonomy tests."""

from __future__ import annotations

from agent.core.abstention import AbstentionReason, classify_abstention


def test_classify_position_exists() -> None:
    reason = classify_abstention(
        ["thesis_open_position_block"],
        signal="HOLD",
    )
    assert reason == AbstentionReason.POSITION_EXISTS


def test_classify_no_edge_conviction() -> None:
    reason = classify_abstention(
        ["no_edge", "conviction_below_entry_floor=0.30<0.35"],
        signal="HOLD",
    )
    assert reason == AbstentionReason.NO_EDGE


def test_soft_quality_not_abstention() -> None:
    reason = classify_abstention(
        ["trade_score_below_min", "score=40.0"],
        signal="HOLD",
    )
    assert reason is None
