"""Unit tests for hypothesis portfolio aggregation.

Paper-trade validation checklist (compare decision_telemetry.ndjson before/after):
- Fewer thesis_direction_conflict and thesis_no_rule_fired HOLDs
- More entries with reduced size_fraction when environment scores are weak
- policy_authority=agent_policy on all DECISION_READY events
- Hard tier still blocks: market_health_hold, has_open_position, portfolio guard
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.core.agent_thesis_engine import AgentThesisEngine, ThesisVerdict
from agent.core.hypothesis_aggregator import (
    aggregate_hypotheses,
    evaluate_all_hypotheses,
    regime_prior,
    thesis_verdict_from_snapshot,
)
from agent.core.hypothesis_types import HypothesisCandidate, MarketHypothesisSnapshot


def _breakout_features() -> dict:
    return {
        "adx_14": 30.0,
        "di_spread": 8.0,
        "vol_regime": 1.25,
        "h_trend": 0.02,
        "rsi_14": 55.0,
        "hurst_60": 0.55,
        "h1_trend": 0.01,
    }


def test_regime_prior_lowers_breakout_in_ranging() -> None:
    assert regime_prior("breakout", "ranging") < regime_prior("breakout", "neutral")
    assert regime_prior("breakout", "ranging") > 0.0


def test_aggregate_near_tie_prefers_direction_not_hold() -> None:
    candidates = [
        HypothesisCandidate(
            id="trend_continuation_long",
            direction="LONG",
            confidence=0.82,
            thesis_type="trend_continuation",
            regime_weight=1.0,
            weighted_confidence=0.82,
        ),
        HypothesisCandidate(
            id="mean_reversion_short",
            direction="SHORT",
            confidence=0.79,
            thesis_type="mean_reversion",
            regime_weight=1.0,
            weighted_confidence=0.79,
        ),
    ]
    env = {"liquidity": 0.8, "trend_strength": 0.7}
    snap = aggregate_hypotheses(candidates, env, "neutral")
    assert snap.aggregate_direction == "LONG"
    assert snap.dominant is not None
    assert snap.dominant.id == "trend_continuation_long"


def test_aggregate_empty_candidates_flat() -> None:
    snap = aggregate_hypotheses([], {}, "ranging")
    assert snap.aggregate_direction == "FLAT"
    assert "hypothesis_no_rule_fired" in snap.reason_codes


def test_thesis_verdict_from_snapshot_adapter() -> None:
    snap = MarketHypothesisSnapshot(
        hypotheses=[],
        environment={"liquidity": 0.7},
        regime="neutral",
        aggregate_direction="LONG",
        aggregate_confidence=0.75,
        hypothesis_margin=0.12,
        dominant=HypothesisCandidate(
            id="breakout_long",
            direction="LONG",
            confidence=0.75,
            thesis_type="breakout",
            horizon_bars=12,
            horizon_minutes=60,
        ),
    )
    v = thesis_verdict_from_snapshot(snap, pos_size=0.05, evidence_contributions={})
    assert v.signal == "LONG"
    assert v.thesis_type == "breakout"
    assert v.intended_horizon_bars == 12


@patch("agent.core.agent_thesis_engine.hypothesis_portfolio_mode", return_value=True)
@patch("agent.core.agent_thesis_engine.settings")
def test_evaluate_all_hypotheses_in_ranging(mock_settings, _portfolio) -> None:
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_trend_enabled = True
    mock_settings.agent_thesis_mean_reversion_enabled = False
    mock_settings.agent_thesis_breakout_adx_min = 25.0
    mock_settings.agent_thesis_breakout_di_min = 5.0
    mock_settings.agent_thesis_breakout_vol_regime_min = 1.1
    mock_settings.jacksparrow_v43_short_execution_enabled = False

    engine = AgentThesisEngine()
    cands = evaluate_all_hypotheses(
        engine, _breakout_features(), "ranging", short_enabled=False
    )
    assert len(cands) >= 1
    assert any(c.thesis_type == "breakout" for c in cands)


@patch("agent.core.agent_thesis_engine.thesis_market_hard_veto_enabled", return_value=True)
@patch("agent.core.agent_thesis_engine.settings")
def test_crisis_hard_veto_when_enabled(mock_settings, _hard) -> None:
    mock_settings.agent_thesis_crisis_veto = True
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_squeeze_veto_threshold = 0.5

    engine = AgentThesisEngine()
    v = engine.evaluate("crisis", {"features": _breakout_features()})
    assert v.signal == "HOLD"
    assert v.thesis_type == "crisis_veto"
