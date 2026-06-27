"""Entry validation guard tests for strategy-first ml_and_thesis mode."""

import pytest

from agent.core.config import settings as app_settings
from agent.core.ml_signal_guard import validate_ml_entry_signal


@pytest.fixture(autouse=True)
def enable_ic_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "require_ic_validation_for_orders", True)


def test_ml_and_thesis_accepts_policy_confirms_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "require_v43_gates_for_entry", False)

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
    assert reason == "agent_thesis_confirms_ml"


def test_ml_and_thesis_rejects_policy_hold() -> None:
    ok, reason = validate_ml_entry_signal(
        signal="HOLD",
        side="BUY",
        model_predictions=[{"model_name": "v43", "confidence": 0.8, "prediction": 0.5}],
        market_context={"trade_score": {"passed": False}},
        policy_verdict={
            "signal": "HOLD",
            "reason_codes": ["fusion_ml_and_thesis_no_agreement"],
        },
    )
    assert ok is False
    assert "policy" in reason


def test_policy_adopted_ml_without_duplicate_strategy_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard trusts policy verdict; strategy/ML agreement is not re-checked here."""
    monkeypatch.setattr(app_settings, "require_v43_gates_for_entry", False)

    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=[{"model_name": "v43", "confidence": 0.8, "prediction": 0.5}],
        market_context={
            "trade_score": {"score": 50.0, "passed": False},
            "ml_validation": {"final_long": True},
        },
        policy_verdict={
            "signal": "BUY",
            "adopted_ml_candidate": True,
            "reason_codes": ["fusion_ml_and_thesis_no_agreement"],
        },
    )
    assert ok is True
    assert reason == "policy_adopted_ml_candidate"
