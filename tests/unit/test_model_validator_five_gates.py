"""Five-gate validation on synthetic holdout."""

from __future__ import annotations

import numpy as np

from agent.learning.adaptive.model_validator import validate_v43_style_five_gates


def test_five_gates_perfect_classifier() -> None:
    n = 200
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, size=n)
    proba = np.zeros((n, 3), dtype=np.float64)
    proba[np.arange(n), y] = 0.99
    proba += 0.01 / 3
    y_pred = y.copy()
    ok, detail = validate_v43_style_five_gates(y, y_pred, proba)
    assert ok is True
    assert detail.get("rejected_reason") is None
