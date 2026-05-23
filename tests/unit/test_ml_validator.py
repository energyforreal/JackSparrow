"""Unit tests for ML validation helpers."""

import pytest

from agent.core.ml_validator import (
    build_ml_validation_from_prediction,
    ml_confirms_direction,
    ml_candidate_signal_from_validation,
    apply_gates_to_ml_validation,
)
from agent.core.strategy_types import MLValidationSnapshot


def test_build_ml_validation_long_raw() -> None:
    ctx = {
        "expected_return": 0.02,
        "threshold": 0.01,
        "short_threshold": 0.01,
        "regime": "trending",
        "unc_scale": 0.9,
    }
    snap = build_ml_validation_from_prediction(ctx, pred_confidence=0.8, pred_value=0.5)
    assert snap.raw_long is True
    assert snap.confirms_long is True
    assert snap.raw_short is False


def test_ml_confirms_direction_long() -> None:
    snap = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="neutral",
        confirms_long=True,
        final_long=True,
    )
    assert ml_confirms_direction(snap, "LONG") is True
    assert ml_confirms_direction(snap, "SHORT") is False


def test_ml_candidate_signal_from_gated_validation() -> None:
    snap = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="neutral",
        model_confidence=0.82,
        final_long=True,
    )
    sig, conf, size = ml_candidate_signal_from_validation(snap, prefer_gated=True)
    assert sig in ("BUY", "STRONG_BUY")
    assert conf == pytest.approx(0.82)


def test_ml_candidate_prefer_gated_holds_without_final_flags() -> None:
    snap = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="neutral",
        model_confidence=0.8,
        confirms_long=True,
        final_long=False,
    )
    sig, _, _ = ml_candidate_signal_from_validation(snap, prefer_gated=True)
    assert sig == "HOLD"


def test_ml_confirms_direction_require_gated() -> None:
    snap = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="neutral",
        confirms_long=True,
        final_long=False,
    )
    assert ml_confirms_direction(snap, "LONG", require_gated=True) is False
    snap.final_long = True
    assert ml_confirms_direction(snap, "LONG", require_gated=True) is True


def test_apply_gates_updates_final_flags() -> None:
    snap = MLValidationSnapshot(
        expected_return=0.02,
        threshold=0.01,
        short_threshold=0.01,
        regime="neutral",
        confirms_long=False,
    )
    apply_gates_to_ml_validation(snap, final_long=True, final_short=False, gate_reject=None)
    assert snap.final_long is True
    assert snap.confirms_long is False
