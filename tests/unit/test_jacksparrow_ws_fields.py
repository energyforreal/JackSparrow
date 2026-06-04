"""WebSocket signal enrichment for JackSparrow v43 and IC rule-based formats."""

from __future__ import annotations

from backend.services.agent_event_subscriber import (
    _jacksparrow_ws_fields_from_predictions,
    _model_consensus_row,
)


def test_ws_fields_from_ic_rule_based_context() -> None:
    preds = [
        {
            "model_name": "JackSparrow_IC_BTCUSD",
            "prediction": 0.12,
            "confidence": 0.55,
            "context": {
                "format": "jacksparrow_ic_rule_based",
                "expected_return": -0.015,
                "threshold": 0.005,
                "regime": "chop",
            },
        }
    ]
    out = _jacksparrow_ws_fields_from_predictions(preds, None)
    assert out["expected_return"] == -0.015
    assert out["threshold"] == 0.005
    assert out["regime"] == "chop"
    assert "edge" in out


def test_ws_fields_ignores_unknown_format() -> None:
    preds = [
        {
            "prediction": 0.5,
            "context": {"format": "legacy_xgb", "expected_return": 0.02},
        }
    ]
    assert _jacksparrow_ws_fields_from_predictions(preds, None) == {}


def test_model_consensus_row_ic_format() -> None:
    pred = {
        "context": {
            "format": "jacksparrow_ic_rule_based",
            "expected_return": 0.008,
            "threshold": 0.005,
            "regime": "bull_trend",
        }
    }
    row = _model_consensus_row("ic", "HOLD", 0.4, 0.1, pred)
    assert row["expected_return"] == 0.008
    assert row["threshold"] == 0.005
    assert row["regime"] == "bull_trend"
