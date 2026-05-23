"""ML signal guard tests for strategy-first ml_and_thesis mode."""

import pytest

from agent.core import ml_signal_guard as guard_mod
from agent.core.ml_signal_guard import validate_ml_entry_signal


def test_ml_and_thesis_requires_confirms_ml_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_mod.settings, "require_ml_signal_for_orders", True)
    monkeypatch.setattr(guard_mod.settings, "agent_policy_mode", "ml_and_thesis")
    monkeypatch.setattr(guard_mod.settings, "require_strategy_ml_agreement", True)
    monkeypatch.setattr(guard_mod.settings, "require_v43_gates_for_entry", False)

    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=[{"model_name": "v43", "confidence": 0.8, "prediction": 0.5}],
        market_context={
            "trade_score": {"score": 80.0, "passed": True},
            "ml_validation": {"final_long": True},
            "v43_execution_profile": {"enabled": True},
            "v43_dedicated_decision": {"enabled": True, "final_long": True},
        },
        policy_verdict={
            "signal": "BUY",
            "adopted_ml_candidate": True,
            "reason_codes": ["agent_thesis_confirms_ml", "fusion_ml_and_thesis_agree"],
        },
    )
    assert ok is True
    assert "confirms_ml" in reason or reason == "policy_adopted_ml_candidate"


def test_ml_and_thesis_rejects_no_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_mod.settings, "require_ml_signal_for_orders", True)
    monkeypatch.setattr(guard_mod.settings, "agent_policy_mode", "ml_and_thesis")
    monkeypatch.setattr(guard_mod.settings, "require_strategy_ml_agreement", True)

    ok, reason = validate_ml_entry_signal(
        signal="HOLD",
        side="BUY",
        model_predictions=[{"model_name": "v43", "confidence": 0.8}],
        market_context={"trade_score": {"passed": False}},
        policy_verdict={
            "signal": "HOLD",
            "reason_codes": ["fusion_ml_and_thesis_no_agreement"],
        },
    )
    assert ok is False
