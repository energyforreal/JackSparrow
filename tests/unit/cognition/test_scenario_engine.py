"""Tests for scenario engine."""

from __future__ import annotations

from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.scenario_engine import evaluate_scenario
from agent.intelligence.cognition.types import MarketMemory, MarketUnderstanding


def test_scenario_compression() -> None:
    inputs = CognitionInputs(
        understanding=MarketUnderstanding(
            symbol="BTCUSD",
            volatility="compressing",
            breakout_status="forming",
        ),
        memory=MarketMemory(symbol="BTCUSD"),
    )
    state, art = evaluate_scenario(inputs)
    assert state.primary in ("compression", "range", "accumulation")
    assert art.module_id == "scenario"
