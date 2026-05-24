"""Step 7 confidence calibration with learning system integration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.core.learning_system import LearningSystem
from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest, ReasoningStep


@pytest.mark.asyncio
async def test_step7_applies_learning_calibration(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_REFLECTION_POLICY_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("REFLECTION_CALIBRATION_MIN_SAMPLES", "1")
    monkeypatch.setenv("LEARNING_STATE_PERSISTENCE_ENABLED", "false")

    from agent.core import config as config_module

    config_module.settings = config_module.Settings()

    learning = LearningSystem()
    await learning.initialize()
    await learning.record_reflection_outcome(
        {
            "quality_score": 0.95,
            "calibration_bucket": "high_confidence_win",
            "was_profitable": True,
            "pnl": 5.0,
            "position_id": "p1",
            "symbol": "BTCUSD",
            "predicted_signal": "BUY",
        }
    )

    engine = MCPReasoningEngine(
        feature_server=None,
        model_registry=None,
        vector_store=None,
        learning_system=learning,
    )

    request = MCPReasoningRequest(symbol="BTCUSD", market_context={})
    steps = [
        ReasoningStep(
            step_number=2,
            step_name="Historical Context Retrieval",
            description="hist",
            evidence=[],
            confidence=0.8,
            timestamp=datetime.now(timezone.utc),
            step_metadata={"historical_win_rate": 0.75},
        ),
        ReasoningStep(
            step_number=3,
            step_name="Model Consensus",
            description="models",
            evidence=[],
            confidence=0.7,
            timestamp=datetime.now(timezone.utc),
        ),
        ReasoningStep(
            step_number=5,
            step_name="Decision Synthesis",
            description="BUY",
            evidence=[],
            confidence=0.7,
            timestamp=datetime.now(timezone.utc),
        ),
        ReasoningStep(
            step_number=6,
            step_name="Trade Adjudication",
            description="BUY approved",
            evidence=[],
            confidence=0.75,
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    model_predictions = [{"model_name": "m1", "confidence": 0.8, "prediction": 0.5}]

    step7 = await engine._step7_confidence_calibration(request, steps, model_predictions)
    assert step7.confidence > 0.0
    assert any("Learning calibration" in e for e in step7.evidence)
