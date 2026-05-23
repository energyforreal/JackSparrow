"""Unit tests for ML-only entry signal enforcement."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.core.ml_signal_guard import validate_ml_entry_signal


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


def test_rejects_without_model_predictions():
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=[],
        market_context=_v43_market_context(final_long=True),
        policy_verdict=_policy_verdict("BUY"),
    )
    assert not ok
    assert "model_predictions" in reason


def test_accepts_v43_long_when_gates_passed():
    with patch("agent.core.ml_signal_guard.settings") as mock_settings:
        mock_settings.require_ml_signal_for_orders = True
        mock_settings.require_v43_gates_for_entry = True
        mock_settings.require_ml_consensus_alignment = True
        mock_settings.jacksparrow_v43_short_execution_enabled = False
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
    assert "v43" in reason


def test_rejects_when_v43_gates_not_passed():
    with patch("agent.core.ml_signal_guard.settings") as mock_settings:
        mock_settings.require_ml_signal_for_orders = True
        mock_settings.require_v43_gates_for_entry = True
        mock_settings.require_ml_consensus_alignment = True
        mock_settings.jacksparrow_v43_short_execution_enabled = False
        ok, reason = validate_ml_entry_signal(
            signal="BUY",
            side="BUY",
            model_predictions=_model_preds(),
            market_context=_v43_market_context(final_long=False),
            policy_verdict=_policy_verdict("BUY"),
        )
    assert not ok
    assert "final_long" in reason or "gate" in reason


def test_rejects_when_policy_did_not_adopt_ml():
    ok, reason = validate_ml_entry_signal(
        signal="BUY",
        side="BUY",
        model_predictions=_model_preds(),
        market_context=_v43_market_context(final_long=True),
        policy_verdict={"signal": "BUY", "adopted_ml_candidate": False},
    )
    assert not ok
    assert "policy" in reason


def test_rejects_policy_adopted_ml_when_ml_validation_gates_failed():
    with patch("agent.core.ml_signal_guard.settings") as mock_settings:
        mock_settings.require_ml_signal_for_orders = True
        mock_settings.require_v43_gates_for_entry = True
        mock_settings.require_ml_consensus_alignment = True
        mock_settings.agent_policy_mode = "ml_only"
        mock_settings.jacksparrow_v43_short_execution_enabled = False
        ok, reason = validate_ml_entry_signal(
            signal="BUY",
            side="BUY",
            model_predictions=_model_preds(),
            market_context=_v43_market_context(final_long=False),
            policy_verdict=_policy_verdict("BUY"),
        )
    assert not ok
    assert (
        "ml_validation" in reason
        or "final_long" in reason
        or "v43_gate_reject" in reason
    )


def test_accepts_thesis_policy_entry_without_v43_gates():
    with patch("agent.core.ml_signal_guard.settings") as mock_settings:
        mock_settings.require_ml_signal_for_orders = True
        mock_settings.require_v43_gates_for_entry = True
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
    assert reason == "policy_thesis_entry"
