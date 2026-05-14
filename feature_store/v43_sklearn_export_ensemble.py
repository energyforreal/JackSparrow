"""Picklable v43-compatible ensemble shell for Colab training exports.

Wraps a sklearn regressor (e.g. ``HistGradientBoostingRegressor``) with
``predict(X, X_df=...)`` so :class:`agent.models.jack_sparrow_v43_node.JackSparrowV43Node`
can call it after ``joblib.load`` (class lives in ``feature_store``, not ``__main__``).
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np


class SklearnRegressorV43Export:
    """Minimal regressor wrapper for v43 inference (expected-return scale)."""

    def __init__(self, reg: Any) -> None:
        self.reg = reg
        self.dynamic_threshold = 0.01
        self.threshold = 0.01

    def predict(self, X: np.ndarray, X_df: Optional[Any] = None) -> np.ndarray:
        Xa = np.asarray(X, dtype=np.float64)
        return np.asarray(self.reg.predict(Xa), dtype=np.float64).ravel()
