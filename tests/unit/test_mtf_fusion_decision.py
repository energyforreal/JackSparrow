"""Tests for fused multi-horizon decision gates and duration selection."""

from __future__ import annotations

from agent.core.fusion_policy import (
    build_fusion_execution_plan,
    evaluate_horizon_forecast,
)
from feature_store.transformer_btcusd.contract import FUSION_GRADE_HIGH, FUSION_GRADE_LOW


def _gates(grade: str = FUSION_GRADE_HIGH, min_p: float = 0.55) -> dict:
    return {
        "horizons": {
            key: {
                "temperature": 1.0,
                "validation_confidence": grade,
                "min_probability": min_p,
            }
            for key in ("h10m", "h30m", "h1h", "h2h")
        }
    }


def _bull_logits() -> list:
    return [0.0, 0.1, 4.0]


def _bear_logits() -> list:
    return [4.0, 0.1, 0.0]


def _neutral_logits() -> list:
    return [0.0, 4.0, 0.0]


def test_longest_accepted_horizon_sets_duration() -> None:
    logits = {
        "h10m": _bull_logits(),
        "h30m": _bull_logits(),
        "h1h": _bull_logits(),
        "h2h": _neutral_logits(),
    }
    gates = _gates()
    gates["horizons"]["h2h"]["validation_confidence"] = FUSION_GRADE_LOW
    verdict = evaluate_horizon_forecast(logits, gates=gates)
    assert verdict.signal in ("BUY", "STRONG_BUY")
    assert verdict.duration_key == "h1h"
    assert verdict.duration_minutes == 60
    plan = build_fusion_execution_plan(verdict)
    assert plan["sl_tp_source"] == "atr"
    assert plan["duration_minutes"] == 60


def test_conflict_holds() -> None:
    logits = {
        "h10m": _bull_logits(),
        "h30m": _bear_logits(),
        "h1h": _neutral_logits(),
        "h2h": _neutral_logits(),
    }
    verdict = evaluate_horizon_forecast(logits, gates=_gates())
    assert verdict.signal == "HOLD"
    assert "horizon_conflict" in verdict.reason_codes


def test_low_grade_rejected() -> None:
    logits = {k: _bull_logits() for k in ("h10m", "h30m", "h1h", "h2h")}
    verdict = evaluate_horizon_forecast(logits, gates=_gates(grade=FUSION_GRADE_LOW))
    assert verdict.signal == "HOLD"
    assert "no_accepted_horizon" in verdict.reason_codes


def test_does_not_pick_highest_probability() -> None:
    """2h may have a higher softmax but LOW grade must not become duration."""
    logits = {
        "h10m": [0.0, 0.2, 2.0],
        "h30m": [0.0, 0.2, 2.0],
        "h1h": _neutral_logits(),
        "h2h": [0.0, 0.0, 8.0],
    }
    gates = _gates()
    gates["horizons"]["h2h"]["validation_confidence"] = FUSION_GRADE_LOW
    verdict = evaluate_horizon_forecast(logits, gates=gates, min_probability=0.5)
    assert verdict.duration_key == "h30m"
    assert verdict.horizons["h2h"].accepted is False
