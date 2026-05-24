"""Unit tests for reasoning chain step numbering and calibration semantics."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.core.reasoning_engine import (
    MCPReasoningEngine,
    MCPReasoningRequest,
    ReasoningStep,
)


def _make_engine() -> MCPReasoningEngine:
    return MCPReasoningEngine(
        feature_server=MagicMock(),
        model_registry=MagicMock(),
        vector_store=None,
    )


def _sample_predictions() -> list[dict]:
    return [
        {
            "model_name": "jacksparrow_v43_BTCUSD",
            "prediction": 0.42,
            "confidence": 0.72,
            "context": {"format": "jacksparrow_v43_multihead"},
        }
    ]


def _v43_market_context(*, adjudication_hold: bool) -> dict:
    return {
        "model_predictions": _sample_predictions(),
        "strategy_candidate": {
            "signal": "BUY",
            "confidence": 0.65,
        },
        "trade_score": {"score": 82.0, "passed": True},
        "ml_validation": {
            "final_long": adjudication_hold is False,
            "confirms_long": adjudication_hold is False,
        },
        "v43_dedicated_decision": {
            "enabled": True,
            "ml_candidate_signal": "BUY" if not adjudication_hold else "HOLD",
        },
    }


@pytest.mark.asyncio
async def test_generate_reasoning_step_numbers_are_unique_and_ordered() -> None:
    engine = _make_engine()
    request = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context=_v43_market_context(adjudication_hold=False),
        use_memory=False,
    )

    chain = await engine.generate_reasoning(request)
    step_numbers = [step.step_number for step in chain.steps]

    assert step_numbers == [1, 2, 3, 4, 5, 6, 7]
    assert len(set(step_numbers)) == len(step_numbers)
    assert chain.steps[-1].step_name == "Confidence Calibration"
    assert chain.steps[-2].step_name == "Trade Adjudication"


@pytest.mark.asyncio
async def test_v43_hold_detection_uses_trade_adjudication_not_synthesis() -> None:
    engine = _make_engine()
    request = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context=_v43_market_context(adjudication_hold=True),
        use_memory=False,
    )

    chain = await engine.generate_reasoning(request)
    calibration = chain.steps[-1]

    assert "HOLD - awaiting policy" in chain.steps[4].description
    assert "HOLD - trade adjudication" in chain.steps[5].description
    assert any("Hold decision: True" in item for item in calibration.evidence)


@pytest.mark.asyncio
async def test_legacy_predictions_key_is_normalized_for_inner_steps() -> None:
    engine = _make_engine()
    request = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context={
            "predictions": _sample_predictions(),
            "strategy_candidate": {"signal": "BUY", "confidence": 0.6},
            "trade_score": {"score": 70.0, "passed": False},
            "ml_validation": {},
            "v43_dedicated_decision": {"enabled": True, "ml_candidate_signal": "HOLD"},
        },
        use_memory=False,
    )

    chain = await engine.generate_reasoning(request)
    consensus = next(step for step in chain.steps if step.step_number == 3)

    assert "No model predictions available" not in " ".join(consensus.evidence)


@pytest.mark.asyncio
async def test_trade_adjudication_has_material_calibration_weight() -> None:
    engine = _make_engine()
    steps = [
        ReasoningStep(
            step_number=1,
            step_name="Situational Assessment",
            description="ok",
            evidence=[],
            confidence=0.5,
            timestamp=datetime.utcnow(),
        ),
        ReasoningStep(
            step_number=6,
            step_name="Trade Adjudication",
            description="BUY - trade adjudication: thesis and ML agree (score=80)",
            evidence=[],
            confidence=0.9,
            timestamp=datetime.utcnow(),
        ),
    ]
    request = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context={"strategy_candidate": {"signal": "BUY"}},
        use_memory=False,
    )

    high_adjudication = await engine._step7_confidence_calibration(
        request,
        steps,
        _sample_predictions(),
    )
    steps[1] = steps[1].model_copy(update={"confidence": 0.1})
    low_adjudication = await engine._step7_confidence_calibration(
        request,
        steps,
        _sample_predictions(),
    )

    assert high_adjudication.confidence > low_adjudication.confidence
