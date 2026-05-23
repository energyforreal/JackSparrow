"""Unit tests for trade confluence scorer."""

from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)
from agent.core.trade_scorer import score_trade_setup


def test_score_passes_with_thesis_and_ml() -> None:
    strategy = StrategyCandidate(
        direction="LONG",
        strength=0.8,
        signal="BUY",
        thesis_type="breakout",
        confidence=0.8,
    )
    ml = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="trending",
        final_long=True,
        confirms_long=True,
    )
    structure = MarketStructureSnapshot(
        market_type="TRENDING",
        regime="trending",
        adx=28.0,
        liquidity_ok=True,
        chop_market=False,
    )
    result = score_trade_setup(
        strategy=strategy,
        ml_validation=ml,
        structure=structure,
        ml_confirms=True,
    )
    assert result.score >= 50.0
    assert result.passed is True


def test_score_skips_ml_points_without_gated_final() -> None:
    strategy = StrategyCandidate(
        direction="LONG",
        strength=0.8,
        signal="BUY",
        thesis_type="breakout",
        confidence=0.8,
    )
    ml = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="trending",
        confirms_long=True,
        final_long=False,
    )
    structure = MarketStructureSnapshot(
        market_type="TRENDING",
        regime="trending",
        adx=28.0,
        liquidity_ok=True,
        chop_market=False,
    )
    result = score_trade_setup(
        strategy=strategy,
        ml_validation=ml,
        structure=structure,
        ml_confirms=True,
    )
    assert result.components.get("ml", 0.0) == 0.0
    assert "score_ml_ungated_skipped" in result.reason_codes


def test_score_fails_flat_thesis() -> None:
    strategy = StrategyCandidate(
        direction="FLAT",
        strength=0.0,
        signal="HOLD",
        thesis_type="flat",
    )
    ml = MLValidationSnapshot(
        expected_return=0.0,
        threshold=0.01,
        short_threshold=0.01,
        regime="neutral",
    )
    structure = MarketStructureSnapshot(market_type="NEUTRAL", regime="neutral")
    result = score_trade_setup(
        strategy=strategy,
        ml_validation=ml,
        structure=structure,
        ml_confirms=False,
    )
    assert result.passed is False
