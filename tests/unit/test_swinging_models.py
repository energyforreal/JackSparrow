"""Model fits stay inside the development span, and strategies share fills."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.swinging.evaluate import compare_strategies, trade_metrics, walk_forward_compare
from research.swinging.fusion import decide
from research.swinging.models import fit_bundle, tune_hyperparameters
from research.swinging.splits import apply_embargo, chronological_bounds, purged_folds


def _frame(rows: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    labels = np.array(["win", "loss", "other"] * rows)[:rows]
    return pd.DataFrame(
        {
            "f1": rng.normal(size=rows),
            "f2": rng.normal(size=rows),
            "f3": rng.normal(size=rows),
            "outcome_class": labels,
            "net_return": rng.normal(scale=0.01, size=rows),
            "direction": np.where(np.arange(rows) % 2 == 0, "long", "short"),
            "algorithmic_score": np.where(np.arange(rows) % 2 == 0, 0.8, 0.2),
            "regime_target": np.where(np.arange(rows) % 2 == 0, "trending", "ranging"),
        }
    )


def test_embargo_drops_the_overlap_window() -> None:
    train, _validation = next(purged_folds(80, n_splits=3, embargo=10))
    assert max(train) <= min(_validation) - 10
    assert apply_embargo([1, 8, 9], 10, 2) == [1]


def test_optuna_does_not_see_the_sealed_tail() -> None:
    pytest.importorskip("optuna")
    pytest.importorskip("xgboost")
    pytest.importorskip("lightgbm")
    frame = _frame()
    tuned = tune_hyperparameters(
        frame,
        ["f1", "f2", "f3"],
        "outcome_class",
        algorithm="xgboost",
        task="classifier",
        n_trials=1,
        study_name="swinging-unit",
    )
    _train_end, _validation_end, sealed = chronological_bounds(len(frame))
    assert tuned["sealed_start"] == sealed
    assert tuned["development_rows"] == sealed
    assert tuned["development_rows"] < len(frame)


def test_fit_bundle_and_strategy_comparison() -> None:
    pytest.importorskip("xgboost")
    pytest.importorskip("lightgbm")
    frame = _frame()
    artifact = fit_bundle(
        frame,
        ["f1", "f2", "f3"],
        target="outcome_class",
        positive_class="win",
        n_trials=0,
    )
    assert artifact["sealed_start"] < len(frame)
    assert artifact["classifier"] is not None

    def predict(train: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
        del train
        validation["win_probability"] = 0.7
        validation["expected_net_return"] = 0.01
        return validation

    report = walk_forward_compare(frame, predict, n_splits=2, embargo=2)
    assert set(report["sealed_test"]) == {"algorithm_only", "ml_only", "hybrid"}
    scored = frame.copy()
    scored["win_probability"] = 0.8
    scored["expected_net_return"] = 0.02
    comparison = compare_strategies(scored)
    assert comparison["algorithm_only"]["trades"] > 0
    assert comparison["hybrid"]["trades"] <= comparison["algorithm_only"]["trades"]
    assert trade_metrics([])["trades"] == 0


def test_hybrid_abstains_when_the_engines_disagree() -> None:
    decision = decide(
        strategy="hybrid",
        direction="long",
        algorithmic_score=0.9,
        win_probability=0.2,
        expected_net_return=-0.01,
    )
    assert decision["action"] == "abstain"
    assert decision["agreement"] == "disagree"
    ml_only = decide(
        strategy="ml_only",
        direction="short",
        algorithmic_score=0.1,
        win_probability=0.8,
        expected_net_return=0.02,
    )
    assert ml_only["action"] == "short"
