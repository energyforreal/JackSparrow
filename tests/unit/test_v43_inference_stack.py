"""Tests for v43 inference stack ablation path."""

from __future__ import annotations

import numpy as np
import pytest

from agent.models.v43_pickle_shims import EnsembleModel


def test_regressor_mean_skips_meta_and_calibrator(monkeypatch: pytest.MonkeyPatch) -> None:
    model = EnsembleModel()

    class _Meta:
        def predict_proba(self, X):
            return np.column_stack([np.zeros(len(X)), np.ones(len(X))])

    class _Cal:
        def predict(self, x):
            return np.full(x.shape[0], 0.99)

    model.meta = _Meta()
    model.calibrator = _Cal()
    model._base_predictions = lambda X: np.array([[0.01, 0.02, 0.03]], dtype=np.float64)

    out_meta = model.predict(np.zeros((1, 3)), inference_stack="meta_calibrator")
    out_reg = model.predict(np.zeros((1, 3)), inference_stack="regressor_mean")
    assert float(out_reg[0]) == pytest.approx(0.02, abs=1e-6)
    assert float(out_meta[0]) != float(out_reg[0])
