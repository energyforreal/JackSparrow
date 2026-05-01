"""F1 validation gate tests."""

import numpy as np
from xgboost import XGBClassifier

from agent.learning.adaptive.model_validator import validate_f1_improvement


def test_validate_f1_improvement_accepts_better() -> None:
    rng = np.random.default_rng(7)
    n = 300
    X = rng.normal(size=(n, 4)).astype(np.float64)
    y = rng.integers(0, 3, size=n).astype(np.int64)
    old = XGBClassifier(
        n_estimators=5,
        max_depth=2,
        learning_rate=0.3,
        objective="multi:softprob",
        num_class=3,
        random_state=1,
    )
    old.fit(X[:200], y[:200])
    new = XGBClassifier(
        n_estimators=80,
        max_depth=4,
        learning_rate=0.05,
        objective="multi:softprob",
        num_class=3,
        random_state=2,
    )
    new.fit(X, y)
    ok, old_f1, new_f1 = validate_f1_improvement(
        {"model": old},
        new,
        X[-50:],
        y[-50:],
        min_improvement=0.0,
    )
    assert isinstance(ok, bool)
    assert 0.0 <= old_f1 <= 1.0
    assert 0.0 <= new_f1 <= 1.0
