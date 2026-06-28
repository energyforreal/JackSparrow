"""Unit tests for evidence engine and conviction sizing."""

from __future__ import annotations

from agent.core.conviction import compute_conviction
from agent.core.evidence_engine import build_evidence_bundle
from agent.core.evidence_types import EvidenceBundle, EvidenceDimension
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)


def test_compute_conviction_weak_setup_small_size() -> None:
    bundle = EvidenceBundle(
        scores={dim.value: 0.25 for dim in EvidenceDimension}
    )
    result = compute_conviction(bundle, "LONG")
    assert result.below_entry_floor
    assert result.size_fraction == 0.0


def test_compute_conviction_strong_setup_sizes() -> None:
    bundle = EvidenceBundle(
        scores={dim.value: 0.75 for dim in EvidenceDimension}
    )
    result = compute_conviction(bundle, "LONG")
    assert not result.below_entry_floor
    assert result.size_fraction >= 0.25
    assert result.conviction >= 0.35


def test_build_evidence_bundle_no_passed_bool() -> None:
    ml = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        uncertainty=0.01,
        final_long=True,
        final_short=False,
        regime="trending",
    )
    structure = MarketStructureSnapshot(
        market_type="TRENDING",
        regime="trending",
        liquidity_ok=True,
        chop_market=False,
    )
    strategy = StrategyCandidate(
        direction="LONG",
        signal="LONG",
        strength=0.6,
        confidence=0.7,
        thesis_type="trend_follow",
    )
    bundle = build_evidence_bundle(
        market_context={"features": {"atr_pct": 0.01}, "multi_horizon_evidence": {"alignment_score": 0.5}},
        ml_validation=ml,
        structure=structure,
        strategy=strategy,
        ml_confirms=True,
    )
    assert "passed" not in bundle.scores
    assert bundle.get(EvidenceDimension.ML_EDGE.value) > 0.4


def test_build_evidence_bundle_includes_environment_metadata() -> None:
    ml = MLValidationSnapshot(
        expected_return=0.01,
        threshold=0.01,
        short_threshold=0.01,
        uncertainty=0.02,
        final_long=False,
        final_short=False,
        regime="neutral",
    )
    structure = MarketStructureSnapshot(
        market_type="NEUTRAL",
        regime="neutral",
        liquidity_ok=True,
        chop_market=False,
    )
    env = {
        "liquidity": 0.77,
        "volatility": 0.31,
        "funding_risk": 0.2,
        "squeeze_prob": 0.1,
        "trend_strength": 0.68,
        "crisis_risk": 0.72,
    }
    bundle = build_evidence_bundle(
        market_context={
            "features": {"atr_pct": 0.01, "vol_regime": 1.0},
            "environment_scores": env,
        },
        ml_validation=ml,
        structure=structure,
        strategy=StrategyCandidate(
            direction="LONG",
            signal="LONG",
            strength=0.5,
        ),
        ml_confirms=False,
    )
    assert bundle.metadata.get("environment") == env
    assert bundle.get("env_liquidity") == 0.77
