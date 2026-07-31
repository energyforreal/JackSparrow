"""Unit tests for transformer-only decision mapping."""

from __future__ import annotations

import pytest

from agent.models.transformer_context_builder import map_prediction_to_signal


def test_map_prediction_buy_signal() -> None:
    signal, conf, codes = map_prediction_to_signal(
        future_return=0.01,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.72,
        min_confidence=0.55,
    )
    assert signal == "STRONG_BUY"
    assert conf == pytest.approx(0.72)
    assert "transformer_long_edge" in codes


def test_map_prediction_hold_below_threshold() -> None:
    signal, conf, codes = map_prediction_to_signal(
        future_return=0.001,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.8,
    )
    assert signal == "HOLD"
    assert "transformer_below_threshold" in codes


def test_map_prediction_extreme_regime_veto() -> None:
    signal, _, codes = map_prediction_to_signal(
        future_return=0.02,
        threshold=0.005,
        vol_regime="EXTREME",
        confidence=0.9,
        extreme_regime_veto=True,
    )
    assert signal == "HOLD"
    assert "transformer_extreme_regime_veto" in codes


def test_map_prediction_low_confidence_hold() -> None:
    signal, _, codes = map_prediction_to_signal(
        future_return=0.02,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.4,
        min_confidence=0.55,
    )
    assert signal == "HOLD"
    assert "transformer_below_min_confidence" in codes
