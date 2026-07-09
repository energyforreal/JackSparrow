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
    sig, _ = conclusion_to_ml_signal_and_size("STRONG_LONG consensus")
    assert sig == "STRONG_LONG"


def test_build_ml_evidence_from_orchestrator_result_shapes() -> None:
    result = {
        "symbol": "BTCUSD",
        "decision": {"signal": "LONG", "confidence": 0.8, "position_size": 0.05},
        "market_context": {"v43_gate_reject": None, "regime": "trend"},
        "models": {"consensus_prediction": 0.2, "consensus_confidence": 0.7, "predictions": []},
        "model_predictions": [],
    }
    snap = build_ml_evidence_from_orchestrator_result(result)
    assert snap.symbol == "BTCUSD"
    assert snap.ml_candidate_signal == "LONG"
    assert snap.source == "v43_orchestrator"


def test_force_hold_vetoes_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", True)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_only")
    engine = AgentPolicyEngine()
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="LONG",
        ml_candidate_confidence=0.9,
        ml_candidate_position_size=0.1,
    )
    v = engine.evaluate(ml_evidence=ev, conclusion="LONG", market_context={})
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
        ml_candidate_signal="SHORT",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
    )
    v = engine.evaluate(ml_evidence=ev, conclusion="SHORT", market_context={})
    assert v.signal == "SHORT"
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
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("LONG"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="HOLD",
        ml_candidate_confidence=0.3,
        ml_candidate_position_size=0.0,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={"features": {}})
    assert v.signal == "LONG"
    assert "agent_thesis_origin" in v.reason_codes
    assert v.adopted_ml_candidate is False


def test_ml_and_thesis_requires_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_and_thesis")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("SHORT"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="LONG",
        ml_candidate_confidence=0.8,
        ml_candidate_position_size=0.05,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "HOLD"
    assert "fusion_ml_and_thesis_no_agreement" in v.reason_codes


def test_ml_and_thesis_adopts_gated_ml_when_thesis_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_and_thesis")
    monkeypatch.setattr(
        ape_mod.settings, "agent_policy_adopt_gated_ml_when_thesis_neutral", True
    )
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.4,
        position_size=0.0,
        reason_codes=["thesis_flat"],
        thesis_type="flat",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="SHORT",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
        ml_confirms=True,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "SHORT"
    assert "fusion_ml_gated_thesis_neutral" in v.reason_codes
    assert v.adopted_ml_candidate is True


def test_ml_and_thesis_adopts_gated_ml_with_aggregate_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aggregate LONG in snapshot relaxes thesis_no_rule_fired block on HOLD thesis."""
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_and_thesis")
    monkeypatch.setattr(
        ape_mod.settings, "agent_policy_adopt_gated_ml_when_thesis_neutral", True
    )
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.0,
        position_size=0.0,
        reason_codes=["thesis_no_rule_fired"],
        thesis_type="flat",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="LONG",
        ml_candidate_confidence=0.75,
        ml_candidate_position_size=0.05,
        ml_confirms=True,
    )
    mctx = {
        "hypothesis_snapshot": {
            "hypotheses": [
                {
                    "id": "breakout_long",
                    "direction": "LONG",
                    "confidence": 0.72,
                    "thesis_type": "breakout",
                    "weighted_confidence": 0.72,
                }
            ],
            "aggregate_direction": "LONG",
            "aggregate_confidence": 0.72,
            "hypothesis_margin": 0.15,
            "environment": {"liquidity": 0.8},
        }
    }
    v = engine.evaluate(ml_evidence=ev, market_context=mctx)
    assert v.signal == "LONG"
    assert "fusion_ml_gated_thesis_neutral" in v.reason_codes


def test_ml_and_thesis_agrees(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_and_thesis")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("LONG"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="LONG",
        ml_candidate_confidence=0.8,
        ml_candidate_position_size=0.05,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "LONG"
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
        ml_candidate_signal="LONG",
        ml_candidate_confidence=0.9,
        ml_candidate_position_size=0.1,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "HOLD"
    assert "thesis_veto_ml_active" in v.reason_codes


def test_ml_or_thesis_blocks_gated_ml_on_hypothesis_no_rule_fired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flat portfolio hypothesis must block gated ML adoption (July 2 ML-only path)."""
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_or_thesis")
    monkeypatch.setattr(
        ape_mod.settings, "agent_policy_adopt_gated_ml_when_thesis_neutral", True
    )
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.0,
        position_size=0.0,
        reason_codes=["hypothesis_no_rule_fired", "regime=neutral"],
        thesis_type="flat",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="SHORT",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
        ml_confirms=True,
    )
    mctx = {
        "hypothesis_snapshot": {
            "aggregate_direction": "FLAT",
            "aggregate_confidence": 0.0,
            "reason_codes": ["hypothesis_no_rule_fired", "regime=neutral"],
        },
        "ml_validation": {"final_long": False, "final_short": True},
    }
    v = engine.evaluate(ml_evidence=ev, market_context=mctx)
    assert v.signal == "HOLD"
    assert v.adopted_ml_candidate is False


def test_flat_hypothesis_gated_ml_override_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3A.2: gated ML may adopt when flat hypothesis override flag is on."""
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_or_thesis")
    monkeypatch.setattr(
        ape_mod.settings, "agent_policy_adopt_gated_ml_when_thesis_neutral", True
    )
    monkeypatch.setattr(
        ape_mod.settings, "agent_policy_allow_gated_ml_on_flat_hypothesis", True
    )
    monkeypatch.setattr(ape_mod.settings, "agent_trade_score_min", 40.0)
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.0,
        position_size=0.0,
        reason_codes=["hypothesis_no_rule_fired", "regime=neutral"],
        thesis_type="flat",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="SHORT",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
        ml_confirms=True,
    )
    mctx = {
        "hypothesis_snapshot": {
            "aggregate_direction": "FLAT",
            "aggregate_confidence": 0.0,
            "reason_codes": ["hypothesis_no_rule_fired", "regime=neutral"],
        },
        "ml_validation": {"final_long": False, "final_short": True},
        "trade_score": 55.0,
    }
    v = engine.evaluate(ml_evidence=ev, market_context=mctx)
    assert v.signal == "SHORT"
    assert v.adopted_ml_candidate is True
    assert any(
        tag in v.reason_codes
        for tag in ("fusion_ml_or_thesis_gated_neutral", "fusion_ml_or_thesis_ml")
    )


def test_flat_hypothesis_override_blocked_without_trade_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_or_thesis")
    monkeypatch.setattr(
        ape_mod.settings, "agent_policy_allow_gated_ml_on_flat_hypothesis", True
    )
    monkeypatch.setattr(ape_mod.settings, "agent_trade_score_min", 40.0)
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.0,
        position_size=0.0,
        reason_codes=["hypothesis_no_rule_fired"],
        thesis_type="flat",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="SHORT",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
        ml_confirms=True,
    )
    mctx = {
        "hypothesis_snapshot": {
            "reason_codes": ["hypothesis_no_rule_fired"],
        },
        "ml_validation": {"final_short": True},
        "trade_score": 10.0,
    }
    v = engine.evaluate(ml_evidence=ev, market_context=mctx)
    assert v.signal == "HOLD"


def test_apply_adjudication_authority_blocks_ml_reject() -> None:
    from agent.core.agent_policy_engine import apply_adjudication_authority
    from agent.core.reasoning_engine import MCPReasoningChain, ReasoningStep

    chain = MCPReasoningChain(
        chain_id="t",
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        market_context={},
        steps=[
            ReasoningStep(
                step_number=6,
                step_name="Trade Adjudication",
                description="HOLD",
                evidence=[],
                confidence=0.3,
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                step_metadata={"adjudication_verdict": "ml_reject"},
            )
        ],
        conclusion="HOLD",
        final_confidence=0.3,
        model_predictions=[],
        feature_context=[],
    )
    from agent.events.schemas import PolicyVerdict

    verdict = PolicyVerdict(
        signal="LONG",
        confidence=0.8,
        position_size=0.05,
        reason_codes=["fusion_ml_or_thesis_thesis"],
        ml_evidence_id="e1",
        adopted_ml_candidate=False,
    )
    out = apply_adjudication_authority(verdict, chain)
    assert out.signal == "HOLD"
    assert "authority_mismatch" in out.reason_codes


def test_ml_or_thesis_blocks_thesis_in_neutral_without_ml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_or_thesis")
    low_conf_eng = MagicMock()
    low_conf_eng.evaluate.return_value = ThesisVerdict(
        signal="LONG",
        confidence=0.5,
        position_size=0.05,
        reason_codes=["thesis_breakout_long"],
        thesis_type="breakout",
    )
    engine = AgentPolicyEngine(thesis_engine=low_conf_eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="HOLD",
        ml_candidate_confidence=0.3,
        ml_candidate_position_size=0.0,
    )
    mctx = {
        "regime": "neutral",
        "ml_validation": {"final_long": False, "final_short": False},
        "strategy_candidate": {"signal": "LONG", "confidence": 0.5},
    }
    v = engine.evaluate(ml_evidence=ev, market_context=mctx)
    assert v.signal == "HOLD"
    assert "thesis_neutral_no_ml_confirm" in v.reason_codes


def test_thesis_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "thesis_only")
    engine = AgentPolicyEngine(thesis_engine=_mock_thesis("LONG"))
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="HOLD",
        ml_candidate_confidence=0.2,
        ml_candidate_position_size=0.0,
    )
    v = engine.evaluate(ml_evidence=ev, market_context={})
    assert v.signal == "LONG"
    assert "agent_thesis_entry" in v.reason_codes
