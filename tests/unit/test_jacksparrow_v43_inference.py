"""Unit tests for JackSparrow v43 inference helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pytest

from agent.models.jacksparrow_v43_inference import (
    ensemble_predict_uncertainty,
    get_regime_model,
    get_short_signal_threshold,
    get_signal_threshold,
    uncertainty_scale,
)


@dataclass
class _FakeEnsemble:
    regime_thresholds: Optional[Dict[str, float]] = None
    dynamic_threshold: float = 0.02
    short_threshold: Optional[float] = None

    def predict_uncertainty(self, X_df: Any) -> np.ndarray:
        return np.array([0.12], dtype=np.float64)


def test_get_signal_threshold_regime_then_floor() -> None:
    m = _FakeEnsemble(regime_thresholds={"ranging": 0.03}, dynamic_threshold=0.02)
    thr = get_signal_threshold("ranging", m, m, floor=0.05)
    assert thr == pytest.approx(0.05)


def test_get_short_signal_threshold_uses_artifact_short_threshold() -> None:
    m = _FakeEnsemble(dynamic_threshold=0.0005, short_threshold=0.0008)
    thr = get_short_signal_threshold("neutral", m, m, floor=0.0001, long_threshold=0.0005)
    assert thr == pytest.approx(0.0008)


def test_get_short_signal_threshold_falls_back_to_long() -> None:
    m = _FakeEnsemble(dynamic_threshold=0.0005, short_threshold=None)
    thr = get_short_signal_threshold(
        "neutral", m, m, floor=0.0001, long_threshold=0.0005
    )
    assert thr == pytest.approx(0.0005)


def test_get_regime_model_crisis_none() -> None:
    m = _FakeEnsemble()
    assert get_regime_model("crisis", {"ranging": m}, m) is None


def test_uncertainty_scale_clip() -> None:
    assert uncertainty_scale(0.05) == pytest.approx(1.0)
    assert uncertainty_scale(0.25) == pytest.approx(0.3)


def test_ensemble_predict_uncertainty_fallback() -> None:
    class NoUnc:
        pass

    u = ensemble_predict_uncertainty(NoUnc(), None)
    assert u == pytest.approx(0.05)
