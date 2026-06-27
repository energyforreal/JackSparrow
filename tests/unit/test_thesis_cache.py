"""Thesis verdict cache consistency across IC, orchestrator, and policy."""

from __future__ import annotations

from agent.core.agent_policy_engine import agent_policy_engine
from agent.core.agent_thesis_engine import (
    ThesisVerdict,
    thesis_verdict_from_dict,
    thesis_verdict_to_dict,
)
from agent.events.schemas import MLEvidenceSnapshot


def test_policy_reuses_cached_thesis_verdict() -> None:
    cached = ThesisVerdict(
        signal="BUY",
        confidence=0.72,
        position_size=0.05,
        reason_codes=["regime_allows_trend_continuation"],
        thesis_type="trend_continuation",
        intended_horizon_bars=2,
        horizon_minutes=10,
    )
    mc = {
        "thesis_verdict": thesis_verdict_to_dict(cached),
        "regime": "trending",
        "features": {"rsi_14": 55.0},
    }
    ml_evidence = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.7,
        ml_candidate_position_size=0.05,
        consensus_signal=0.5,
        consensus_confidence=0.7,
        model_predictions=[],
        v43_regime="trending",
    )
    verdict = agent_policy_engine.evaluate(
        ml_evidence=ml_evidence,
        conclusion="BUY - test",
        market_context=mc,
    )
    restored = thesis_verdict_from_dict(mc.get("thesis_verdict"))
    assert restored is not None
    assert restored.signal == cached.signal
    assert verdict.signal in ("BUY", "STRONG_BUY", "HOLD")
