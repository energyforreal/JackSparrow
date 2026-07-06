"""Scorer monotonicity: higher expectation confidence -> higher adjusted confidence."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.strategy_scorer import score_strategies
from agent.intelligence.cognition.strategy_selector import select_strategies
from agent.intelligence.cognition.types import (
    ExpectationHorizon,
    ExpectationState,
    MarketUnderstanding,
    ScenarioState,
    StrategySelectionEntry,
    StrategySelectionResult,
)


def _understanding() -> MarketUnderstanding:
    return MarketUnderstanding(
        symbol="BTCUSD",
        bar_index=1,
        trend="bullish",
        trend_strength="moderate",
        trend_age_candles=5,
        momentum="increasing",
        breakout_status="forming",
        retest_status="none",
        structure="BULLISH",
        liquidity="healthy",
        volatility="expanding",
        regime="neutral",
        confidence="medium",
        direction_bias="LONG",
        regime_benchmark="breakout",
        mtf=(("h1", "context_bullish"), ("m15", "setup_bullish"), ("m5", "execution_wait")),
    )


def _expectation(confidence: float) -> ExpectationState:
    bl = min(0.95, max(0.3, confidence))
    horizons = (
        ExpectationHorizon(
            horizon_minutes=30,
            trend_persistence=0.6,
            breakout_likelihood=bl,
            reversal_risk=0.25,
            volatility_expansion=0.7,
            liquidity_sweep_risk=0.0,
        ),
    )
    return ExpectationState(
        horizons=horizons,
        dominant_expectation="breakout",
        confidence=confidence,
        delta_from_prior=0.0,
        revision_drivers=(),
        reason_codes=(),
    )


def _eligible_breakout_selection() -> StrategySelectionResult:
    return StrategySelectionResult(
        entries=(
            StrategySelectionEntry(
                profile_id="breakout",
                eligible=True,
                abstention_reason=None,
            ),
        )
    )


def test_breakout_score_increases_with_expectation_confidence() -> None:
    scores: list[float] = []
    for conf in (0.30, 0.50, 0.80, 0.95):
        inputs = CognitionInputs(
            understanding=_understanding(),
            scenario=ScenarioState(
                primary="expansion",
                confidence=0.7,
                sub_signals=("breakout_forming",),
                previous_primary=None,
                revision_reason=None,
                reason_codes=("scenario_expansion",),
            ),
            expectation=_expectation(conf),
            features={"adx_14": 28.0, "bb_width": 1.2, "vol_regime": 1.2},
        )
        sel = _eligible_breakout_selection()
        result, _ = score_strategies(inputs, sel)
        breakout = next(e for e in result.entries if e.profile_id == "breakout")
        scores.append(breakout.adjusted_confidence)
    assert scores == sorted(scores)
    assert scores[-1] > scores[0]


def test_selector_and_scorer_run_without_error() -> None:
    inputs = CognitionInputs(
        understanding=_understanding(),
        expectation=_expectation(0.75),
        features={"adx_14": 30.0},
    )
    sel, _ = select_strategies(inputs)
    scores, _ = score_strategies(inputs, sel)
    assert scores.consensus_direction in ("FLAT", "LONG", "SHORT")
