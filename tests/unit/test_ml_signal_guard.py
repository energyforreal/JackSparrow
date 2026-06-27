"""Unit tests for IC entry signal enforcement (entry_validation_guard shim)."""

from __future__ import annotations

import pytest

from agent.core.config import settings as app_settings
from agent.core.ml_signal_guard import validate_ml_entry_signal


@pytest.fixture(autouse=True)
def enable_ic_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "require_ic_validation_for_orders", True)


def _v43_market_context(*, final_long: bool = False, final_short: bool = False) -> dict:
    desired = "long" if final_long else ("short" if final_short else None)
    gate_reject = None if (final_long or final_short) else "min_edge_cost"
    return {
        "v43_execution_profile": {
            "enabled": True,
            "desired_side": desired,
        },
        "v43_dedicated_decision": {
            "enabled": True,
            "final_long": final_long,
            "final_short": final_short,
        },
        "ml_validation": {
            "final_long": final_long,
            "final_short": final_short,
            "confirms_long": final_long,
            "confirms_short": final_short,
        },
        "v43_gate_reject": gate_reject,
        "consensus_signal": 0.8 if final_long else (-0.8 if final_short else 0.0),
    }


def _policy_verdict(signal: str) -> dict:
    return {
        "signal": signal,
        "adopted_ml_candidate": True,
        "authority": "agent_policy",
        "reason_codes": ["fusion_ml_or_thesis_ml", "policy_adopted_ml_candidate"],
    }


def _model_preds() -> list:
    return [
        {
            "model_name": "jacksparrow_v43_BTCUSD",
            "prediction": 1,
            "confidence": 0.85,
            "healthy": True,
        }
    ]


def test_rejects_without_model_predictions() -> None:
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=[],
        market_context=_v43_market_context(final_long=True),
        policy_verdict=_policy_verdict("BUY"),
    )
    assert not ok
    assert "healthy" in reason or "ic_predictions" in reason


def test_accepts_v43_long_when_gates_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "require_v43_gates_for_entry", True)
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=_model_preds(),
        market_context=_v43_market_context(final_long=True),
        ml_evidence_snapshot={
            "ml_candidate_signal": "BUY",
            "model_predictions": _model_preds(),
        },
        policy_verdict=_policy_verdict("BUY"),
    )
    assert ok
    assert "ic_validation" in reason


def test_rejects_when_v43_gates_not_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "require_v43_gates_for_entry", True)
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=_model_preds(),
        market_context=_v43_market_context(final_long=False),
        policy_verdict=_policy_verdict("BUY"),
    )
    assert not ok
    assert "final_long" in reason or "gate" in reason or "ic_validation" in reason


def test_rejects_when_policy_did_not_adopt_ml() -> None:
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=_model_preds(),
        market_context=_v43_market_context(final_long=True),
        policy_verdict={"signal": "BUY", "adopted_ml_candidate": False},
    )
    assert not ok
    assert "policy" in reason


def test_rejects_policy_adopted_ml_when_ic_validation_gates_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_settings, "require_v43_gates_for_entry", True)
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=_model_preds(),
        market_context=_v43_market_context(final_long=False),
        policy_verdict=_policy_verdict("BUY"),
    )
    assert not ok
    assert "ic_validation" in reason or "final_long" in reason or "gate" in reason


def test_accepts_thesis_policy_entry_without_v43_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_settings, "require_v43_gates_for_entry", False)
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=_model_preds(),
        market_context=_v43_market_context(final_long=False),
        policy_verdict={
            "signal": "BUY",
            "adopted_ml_candidate": False,
            "reason_codes": ["agent_thesis_entry", "agent_thesis_origin"],
        },
    )
    assert ok
    assert reason in (
        "agent_thesis_entry",
        "agent_thesis_origin",
        "policy_thesis_entry",
    )
