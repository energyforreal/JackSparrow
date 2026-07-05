"""Tests for entry economic hard veto."""

from __future__ import annotations

from unittest.mock import patch

from agent.core.entry_quality import EntryQualityResult, apply_entry_quality_policy
from agent.core.strategy_types import MLValidationSnapshot
from agent.events.schemas import PolicyVerdict


def test_economic_hard_veto_blocks_low_edge():
    verdict = PolicyVerdict(
        signal="LONG",
        confidence=0.7,
        position_size=1.0,
        reason_codes=[],
    )
    eq = EntryQualityResult(
        quality_score=70.0,
        passed=True,
        dimensions={"economic": 0.8},
        reason_codes=[],
    )
    ml = MLValidationSnapshot(
        expected_return=0.0001,
        threshold=0.5,
        short_threshold=0.5,
        regime="neutral",
        raw_long=True,
        raw_short=False,
        confirms_long=True,
        confirms_short=False,
    )
    with patch("agent.core.entry_quality.settings") as s:
        s.entry_economic_hard_veto_enabled = True
        s.entry_economic_min_edge_cost_multiplier = 1.0
        s.entry_quality_min_score = 55.0
        with patch("agent.core.entry_quality.round_trip_cost_pct", return_value=0.002):
            out = apply_entry_quality_policy(
                verdict, eq, True, ml_validation=ml
            )
    assert out.signal == "HOLD"
    assert "economic_hard_veto" in out.reason_codes
