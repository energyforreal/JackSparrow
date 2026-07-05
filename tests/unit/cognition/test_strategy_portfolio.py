"""Tests for strategy selector and scorer."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.strategy_selector import select_strategies
from agent.intelligence.cognition.strategy_scorer import score_strategies
from agent.intelligence.cognition.types import (
    ExpectationHorizon,
    ExpectationState,
    MarketUnderstanding,
    RiskIntelligenceState,
    ScenarioState,
)


def test_mean_reversion_ineligible_in_markup() -> None:
    inputs = CognitionInputs(
        understanding=MarketUnderstanding(symbol="BTCUSD", trend="bullish", direction_bias="LONG"),
        scenario=ScenarioState(primary="markup", confidence=0.8),
        expectation=ExpectationState(
            horizons=(
                ExpectationHorizon(
                    horizon_minutes=30,
                    trend_persistence=0.8,
                    breakout_likelihood=0.3,
                    reversal_risk=0.2,
                ),
            ),
            dominant_expectation="trend_continuation",
            confidence=0.8,
        ),
        risk_intelligence=RiskIntelligenceState(trade_environment_score=0.7),
    )
    sel, _ = select_strategies(inputs)
    by_id = {e.profile_id: e for e in sel.entries}
    assert by_id["mean_reversion"].eligible is False
    assert by_id["trend_continuation"].eligible is True


def test_scorer_produces_consensus() -> None:
    inputs = CognitionInputs(
        understanding=MarketUnderstanding(symbol="BTCUSD", direction_bias="LONG"),
        scenario=ScenarioState(primary="markup"),
        expectation=ExpectationState(
            horizons=(ExpectationHorizon(horizon_minutes=30, trend_persistence=0.85),),
            confidence=0.85,
        ),
        risk_intelligence=RiskIntelligenceState(trade_environment_score=0.75),
    )
    sel, _ = select_strategies(inputs)
    scores, art = score_strategies(inputs, sel)
    assert art.module_id == "strategy_scorer"
    assert scores.consensus_direction in ("LONG", "FLAT", "MIXED", "SHORT")
