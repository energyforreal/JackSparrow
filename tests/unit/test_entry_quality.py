"""Unit tests for entry quality evaluator."""

from agent.core.entry_quality import evaluate_entry_quality
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)


def _strategy(direction: str = "LONG", conf: float = 0.75) -> StrategyCandidate:
    return StrategyCandidate(
        direction=direction,
        strength=0.7,
        signal=direction,
        thesis_type="breakout",
        confidence=conf,
    )


def _ml(final_long: bool = True, proba: float = 0.01, thr: float = 0.005) -> MLValidationSnapshot:
    return MLValidationSnapshot(
        expected_return=proba,
        threshold=thr,
        short_threshold=thr,
        regime="trending",
        final_long=final_long,
        final_short=False,
        uncertainty=0.02,
    )


def _structure() -> MarketStructureSnapshot:
    return MarketStructureSnapshot(
        market_type="TRENDING",
        regime="trending",
        liquidity_ok=True,
        chop_market=False,
    )


def test_entry_quality_passes_aligned_thesis_ml() -> None:
    result = evaluate_entry_quality(
        strategy=_strategy(),
        ml_validation=_ml(),
        structure=_structure(),
        ml_confirms=True,
        market_context={
            "regime": "trending",
            "gate5_economic": {"pass": True},
            "features": {"hurst_60": 0.6, "spread_bps": 5.0},
        },
        collapse_rate=0.1,
    )
    assert result.quality_score >= 55.0
    assert result.passed is True
    assert "structural" in result.dimensions


def test_entry_quality_fails_flat_hypothesis_ml_only() -> None:
    result = evaluate_entry_quality(
        strategy=StrategyCandidate(
            direction="FLAT",
            strength=0.0,
            signal="HOLD",
            thesis_type="flat",
            confidence=0.0,
        ),
        ml_validation=_ml(final_long=False, proba=-0.02),
        structure=_structure(),
        ml_confirms=False,
        market_context={
            "regime": "neutral",
            "hypothesis_snapshot": {
                "aggregate_direction": "FLAT",
                "aggregate_confidence": 0.0,
            },
            "gate5_economic": {"pass": False},
        },
        collapse_rate=0.97,
    )
    assert result.passed is False
    assert result.dimensions["ml"] < 0.5


def test_collapse_reduces_ml_dimension() -> None:
    low = evaluate_entry_quality(
        strategy=_strategy(),
        ml_validation=_ml(),
        structure=_structure(),
        ml_confirms=True,
        market_context={"regime": "trending", "gate5_economic": {"pass": True}},
        collapse_rate=0.1,
    )
    high = evaluate_entry_quality(
        strategy=_strategy(),
        ml_validation=_ml(),
        structure=_structure(),
        ml_confirms=True,
        market_context={"regime": "trending", "gate5_economic": {"pass": True}},
        collapse_rate=0.97,
    )
    assert high.dimensions["ml"] < low.dimensions["ml"]
