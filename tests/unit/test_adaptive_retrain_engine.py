"""Tests for warm-start retrain helpers."""

import numpy as np
import pytest
from xgboost import XGBClassifier

from agent.learning.adaptive.retrain_engine import (
    class_weights_to_sample_weight,
    prepare_training_matrix,
    warm_start_retrain,
)


def test_class_weights_to_sample_weight() -> None:
    y = np.array([0, 1, 2, 0])
    w = class_weights_to_sample_weight(y, {0: 1.3, 1: 0.5, 2: 1.3})
    assert w[0] == pytest.approx(1.3)
    assert w[1] == pytest.approx(0.5)
    assert w[2] == pytest.approx(1.3)


def test_prepare_training_matrix() -> None:
    import pandas as pd

    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, np.nan, 4.0],
            "b": [0.0, 1.0, 2.0, 3.0],
            "label": [0, 1, 2, 0],
        }
    )
    clean, X, med = prepare_training_matrix(df, ["a", "b"])
    assert len(clean) >= 1
    assert X.shape[1] == 2
    assert "a" in med.index or "a" in med  # Series


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_warm_start_retrain_round_trip() -> None:
    rng = np.random.default_rng(1)
    n = 400
    X = rng.normal(size=(n, 6)).astype(np.float64)
    y = rng.integers(0, 3, size=n).astype(np.int64)
    sw = np.ones(n, dtype=np.float64)
    old = XGBClassifier(
        n_estimators=20,
        max_depth=3,
        learning_rate=0.1,
        objective="multi:softprob",
        num_class=3,
        random_state=42,
    )
    old.fit(X, y, sample_weight=sw)
    bundle = {"model": old, "features": [f"f{i}" for i in range(6)], "meta": {}}
    new = warm_start_retrain(bundle, X, y, sw, num_boost_round=10)
    assert new.predict(X[:5]).shape == (5,)
