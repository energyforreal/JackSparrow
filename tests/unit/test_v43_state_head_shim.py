"""StateHeadModel and MultiHeadBundle.state_heads round-trip."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from agent.models.v43_pickle_shims import MultiHeadBundle, StateHeadModel


class _StubClf:
    def predict_proba(self, X):
        p1 = np.full(len(X), 0.7, dtype=np.float64)
        return np.column_stack([1.0 - p1, p1])


def test_state_head_model_predict_scalar_score():
    model = StateHeadModel()
    model.classifier = _StubClf()
    model.feature_cols = [f"f{i}" for i in range(5)]
    model.head_key = "trade_quality"
    model.head_type = "binary"
    model.classes_ = ["sl_first", "tp_first"]
    model._is_fitted = True
    X = np.zeros((1, 5), dtype=np.float32)
    score = model.predict_scalar_score(X)
    assert score == pytest.approx(0.7, abs=0.01)


def test_multihead_bundle_state_heads():
    bundle = MultiHeadBundle()
    sh = StateHeadModel()
    sh.head_key = "regime"
    bundle.set_state_head("regime", sh)
    assert bundle.get_state_head("regime") is sh
    assert "regime" in bundle.state_head_keys()
