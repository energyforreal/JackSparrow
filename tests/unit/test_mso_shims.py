"""Unit tests for MSO bundle inference decode."""

from __future__ import annotations

import numpy as np

from agent.models.market_state_shims import (
    MarketStateBundleExport,
    _decode_class_code,
    _proba_to_label_map,
)


class _MockMulticlassModel:
    """Minimal sklearn-like multiclass model with LabelEncoder integer classes_."""

    def __init__(self, pred_code: int, proba: np.ndarray):
        self.classes_ = np.array([0, 1, 2])
        self._pred_code = int(pred_code)
        self._proba = np.asarray(proba, dtype=np.float64)

    def predict(self, X):
        return np.array([self._pred_code])

    def predict_proba(self, X):
        return self._proba.reshape(1, -1)


def test_decode_class_code_maps_label_encoder_indices():
    class_order = ("STRONG_BULL", "WEAK_BULL", "RANGE", "WEAK_BEAR", "STRONG_BEAR")
    model = _MockMulticlassModel(pred_code=2, proba=np.array([0.1, 0.1, 0.7, 0.05, 0.05]))
    model.classes_ = np.array([0, 1, 2, 3, 4])
    assert _decode_class_code(2, class_order, model) == "RANGE"
    assert _decode_class_code(0, class_order, model) == "STRONG_BULL"
    assert _decode_class_code(0, class_order, model) != "0"


def test_predict_horizon_returns_string_labels():
    class_order = ("BULL", "RANGE", "BEAR")
    clf = _MockMulticlassModel(pred_code=1, proba=np.array([0.15, 0.70, 0.15]))
    bundle = MarketStateBundleExport(
        horizon_models={"intraday_30m": {"trend_regime": clf}},
        feature_cols=["a", "b", "c"],
        state_dimensions=("trend_regime",),
        class_orders={"intraday_30m:trend_regime": class_order},
    )
    row = np.random.default_rng(2).normal(size=(1, 3))
    out = bundle.predict_horizon("intraday_30m", row)
    assert out["trend_regime"] == "RANGE"
    proba = out["trend_regime_proba"]
    assert set(proba.keys()) == set(class_order)
    assert "0" not in proba


def test_proba_to_label_map_string_keys():
    class_order = ("NO_BREAKOUT", "BREAKOUT_FORMING")
    proba = np.array([0.7, 0.3])
    model = _MockMulticlassModel(pred_code=0, proba=proba)
    prob_map = _proba_to_label_map(proba, class_order, model)
    assert prob_map["NO_BREAKOUT"] == 0.7
    assert prob_map["BREAKOUT_FORMING"] == 0.3
    assert "0" not in prob_map
