"""Agent policy engine: ML evidence vs agent ratification / veto."""

from unittest.mock import AsyncMock

import pytest

from agent.core import agent_policy_engine as ape_mod
from agent.core.agent_policy_engine import (
    AgentPolicyEngine,
    build_ml_evidence_from_orchestrator_result,
    conclusion_to_ml_signal_and_size,
)
from agent.events.schemas import MLEvidenceSnapshot


def test_conclusion_strong_buy_before_buy() -> None:
    sig, _ = conclusion_to_ml_signal_and_size("STRONG_BUY consensus")
    assert sig == "STRONG_BUY"


def test_build_ml_evidence_from_orchestrator_result_shapes() -> None:
    result = {
        "symbol": "BTCUSD",
        "decision": {"signal": "BUY", "confidence": 0.8, "position_size": 0.05},
        "market_context": {"v43_gate_reject": None, "regime": "trend"},
        "models": {"consensus_prediction": 0.2, "consensus_confidence": 0.7, "predictions": []},
        "model_predictions": [],
    }
    snap = build_ml_evidence_from_orchestrator_result(result)
    assert snap.symbol == "BTCUSD"
    assert snap.ml_candidate_signal == "BUY"
    assert snap.source == "v43_orchestrator"


def test_force_hold_vetoes_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", True)
    engine = AgentPolicyEngine()
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.9,
        ml_candidate_position_size=0.1,
    )
    v = engine.evaluate(ml_evidence=ev, conclusion="BUY", market_context={})
    assert v.signal == "HOLD"
    assert "agent_policy_force_hold" in v.reason_codes
    assert v.adopted_ml_candidate is False


def test_default_ratifies_ml_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    engine = AgentPolicyEngine()
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="SELL",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
    )
    v = engine.evaluate(ml_evidence=ev, conclusion="SELL", market_context={})
    assert v.signal == "SELL"
    assert v.adopted_ml_candidate is True
    assert "agent_ratified_ml_evidence" in v.reason_codes
