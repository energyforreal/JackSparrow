"""Tests for reflection-driven learning feedback loop."""

from __future__ import annotations

import pytest

from agent.core.learning_system import LearningSystem


@pytest.mark.asyncio
async def test_record_reflection_outcome_updates_global_factor(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_REFLECTION_POLICY_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("REFLECTION_CALIBRATION_MIN_SAMPLES", "2")
    monkeypatch.setenv("LEARNING_STATE_PERSISTENCE_ENABLED", "false")

    from agent.core import config as config_module

    config_module.settings = config_module.Settings()

    learning = LearningSystem()
    await learning.initialize()

    reflection = {
        "quality_score": 0.9,
        "calibration_bucket": "high_confidence_win",
        "was_profitable": True,
        "pnl": 10.0,
        "position_id": "p1",
        "symbol": "BTCUSD",
        "predicted_signal": "BUY",
    }
    await learning.record_reflection_outcome(reflection)
    await learning.record_reflection_outcome(reflection)

    factor = learning.confidence_calibration.get_reflection_factor()
    assert factor >= 1.0

    calibrated, diagnostics = await learning.calibrate_reasoning_confidence(
        0.7,
        [{"model_name": "m1", "confidence": 0.8}],
        historical_win_rate=0.66,
    )
    assert 0.0 <= calibrated <= 1.0
    assert diagnostics.get("reflection_global_factor") is not None


@pytest.mark.asyncio
async def test_record_reflection_skipped_when_flag_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_REFLECTION_POLICY_FEEDBACK_ENABLED", "false")
    monkeypatch.setenv("LEARNING_STATE_PERSISTENCE_ENABLED", "false")

    from agent.core import config as config_module

    config_module.settings = config_module.Settings()

    learning = LearningSystem()
    await learning.initialize()
    before = learning.confidence_calibration.global_reflection_factor

    await learning.record_reflection_outcome({"quality_score": 0.1, "calibration_bucket": "x"})
    assert learning.confidence_calibration.global_reflection_factor == before
