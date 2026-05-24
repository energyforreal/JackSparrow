"""Unit tests for v43 regime classifier coercion guard."""

from __future__ import annotations

import numpy as np

from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
from agent.models.v43_pickle_shims import EnsembleModel


class _FakeClassifierSubmodel:
    def predict(self, X, X_df=None):
        return np.array([0.72], dtype=np.float64)


def test_predict_active_falls_back_to_head_when_guard_enabled() -> None:
    node = JackSparrowV43Node.__new__(JackSparrowV43Node)
    node._model_name = "jacksparrow_v43_BTCUSD"
    head = EnsembleModel()
    head.predict = lambda X, X_df=None: np.array([0.0025], dtype=np.float64)  # type: ignore[method-assign]
    sub = _FakeClassifierSubmodel()

    out, diag = node._predict_active(
        sub,
        head,
        np.zeros((1, 2)),
        None,
        horizon_key="h1",
        regime="ranging",
        guard_enabled=True,
    )

    assert float(out[0]) == 0.0025
    assert diag["ensemble_fallback"] is True
    assert diag["coerced"] is False
    assert diag["model_origin"] == "global_ensemble"


def test_predict_active_coerces_when_guard_disabled() -> None:
    node = JackSparrowV43Node.__new__(JackSparrowV43Node)
    node._model_name = "jacksparrow_v43_BTCUSD"
    head = EnsembleModel()
    sub = _FakeClassifierSubmodel()

    out, diag = node._predict_active(
        sub,
        head,
        np.zeros((1, 2)),
        None,
        horizon_key="h1",
        regime="ranging",
        guard_enabled=False,
    )

    assert float(out[0]) == (0.72 - 0.5) * 0.04
    assert diag["coerced"] is True
    assert diag["ensemble_fallback"] is False
