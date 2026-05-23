"""Unit tests for v43 expected-return scale guards on regime models."""

from __future__ import annotations

import numpy as np

from agent.models.jack_sparrow_v43_node import (
    _coerce_probability_to_return_scale,
    _looks_like_classifier_probability,
    _sanitize_expected_return,
)


class _FakeClassifierRegime:
    """Stand-in for LGBMModel regime wrapper."""


def test_looks_like_classifier_probability_detects_unit_interval() -> None:
    arr = np.array([0.55, 0.62, 0.58], dtype=np.float64)
    assert _looks_like_classifier_probability(arr) is True


def test_sanitize_coerces_regime_classifier_output() -> None:
    arr = np.array([0.7], dtype=np.float64)
    out = _sanitize_expected_return(
        arr,
        active_model=_FakeClassifierRegime(),
        model_name="test_regime",
    )
    assert float(out[0]) == _coerce_probability_to_return_scale(arr)[0]
    assert -0.02 <= float(out[0]) <= 0.02


def test_sanitize_leaves_ensemble_small_returns() -> None:
    from agent.models.v43_pickle_shims import EnsembleModel

    arr = np.array([0.0012, -0.0008], dtype=np.float64)
    out = _sanitize_expected_return(
        arr,
        active_model=EnsembleModel(),
        model_name="test_ensemble",
    )
    np.testing.assert_allclose(out, arr)
