"""Agent policy engine: ML evidence vs agent ratification / fusion."""

from unittest.mock import MagicMock, patch

import pytest

from agent.core import agent_policy_engine as ape_mod
from agent.core.agent_policy_engine import (
    AgentPolicyEngine,
    build_ml_evidence_from_orchestrator_result,
    conclusion_to_ml_signal_and_size,
)
from agent.core.agent_thesis_engine import ThesisVerdict
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
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_only")
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
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_only")
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


def _mock_thesis(signal: str, thesis_type: str = "breakout") -> MagicMock:
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal=signal,
        confidence=0.75,
        position_size=0.05,
        reason_codes=["thesis_breakout_long"],
        thesis_type=thesis_type,
    )
    return eng


def test_ml_or_thesis_uses_thesis_when_ml_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_or_thesis")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("BUY"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="HOLD",
        ml_candidate_confidence=0.3,
        ml_candidate_position_size=0.0,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={"features": {}})
    assert v.signal == "BUY"
    assert "agent_thesis_origin" in v.reason_codes
    assert v.adopted_ml_candidate is False


def test_ml_and_thesis_requires_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_and_thesis")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("SELL"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.8,
        ml_candidate_position_size=0.05,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "HOLD"
    assert "fusion_ml_and_thesis_no_agreement" in v.reason_codes


def test_ml_and_thesis_agrees(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_and_thesis")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("BUY"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.8,
        ml_candidate_position_size=0.05,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "BUY"
    assert v.adopted_ml_candidate is True
    assert "agent_thesis_confirms_ml" in v.reason_codes


def test_thesis_veto_ml_blocks_on_crisis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "thesis_veto_ml")
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.0,
        position_size=0.0,
        reason_codes=["thesis_crisis_regime_veto"],
        thesis_type="crisis_veto",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.9,
        ml_candidate_position_size=0.1,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "HOLD"
    assert "thesis_veto_ml_active" in v.reason_codes


def test_thesis_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "thesis_only")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("BUY"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="HOLD",
        ml_candidate_confidence=0.2,
        ml_candidate_position_size=0.0,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "BUY"
    assert "agent_thesis_entry" in v.reason_codes
