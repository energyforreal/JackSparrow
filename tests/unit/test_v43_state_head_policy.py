"""Policy fusion and uncertainty gate tests for state heads."""

from __future__ import annotations

import pytest

from agent.core.agent_policy_engine import (
    _state_head_policy_blocks_entry,
    _state_head_scores_from_context,
)
from agent.events.schemas import MLEvidenceSnapshot
from agent.core.config import settings
from agent.core.v43_signal_gates import V43GateState, apply_uncertainty_gate


def test_state_head_policy_blocks_low_regime(monkeypatch):
    monkeypatch.setattr(settings, "jacksparrow_v43_state_heads_enabled", True)
    monkeypatch.setattr(settings, "jacksparrow_v43_state_head_policy_enabled", True)
    monkeypatch.setattr(settings, "jacksparrow_v43_regime_min", 0.60)
    scores = {
        "p_regime_favorable": 0.40,
        "p_setup_quality": 0.70,
        "p_vol_expansion": 0.55,
        "uncertainty_score": 0.01,
    }
    blocked, reasons = _state_head_policy_blocks_entry(scores)
    assert blocked
    assert any("regime" in r for r in reasons)


def test_state_head_scores_from_context():
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        ml_candidate_signal="HOLD",
        p_regime_favorable=0.75,
    )
    scores = _state_head_scores_from_context(
        {"p_setup_quality": 0.65, "uncertainty_score": 0.01},
        ev,
    )
    assert scores["p_regime_favorable"] == 0.75
    assert scores["p_setup_quality"] == 0.65


def test_uncertainty_gate_rejects_high_disagreement(monkeypatch):
    monkeypatch.setattr(settings, "jacksparrow_v43_uncertainty_max", 0.02)
    state = V43GateState()
    res = apply_uncertainty_gate(0.05, state)
    assert not res.allow
    assert res.reject_reason == "high_uncertainty"
