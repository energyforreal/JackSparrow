"""Colab search, correlation, and notebook structure for recognition."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.recognition_15m.colab import (
    assert_recognition_report,
    final_train_stride,
    perturbation_indices,
)
from research.recognition_15m.contract import ENGINEERED_CHANNELS, GEOMETRIC_CLASSES, WINDOW_BARS
from research.recognition_15m.dataset import prepare_series
from research.recognition_15m.explain import aggregate_shap_to_channels, spearman_report
from research.recognition_15m.search import assert_folds_exclude_test, run_optuna_search
from research.recognition_15m.splits import development_folds, purged_split


def _walk(count: int, seed: int = 4) -> pd.DataFrame:
    """Random 15-minute walk with valid OHLC."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.3, count))
    open_ = np.empty(count, dtype=np.float64)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=count, freq="15min", tz="UTC"),
            "open": open_,
            "high": np.maximum(open_, close) + 0.2,
            "low": np.minimum(open_, close) - 0.2,
            "close": close,
            "volume": rng.uniform(1.0, 4.0, count),
        }
    )


def test_development_folds_keep_a_purge_and_exclude_the_test() -> None:
    """Inner folds stay inside the development span."""
    splits = purged_split(np.arange(4000))
    folds = development_folds(splits["train"], splits["val"])
    assert len(folds) == 3
    assert_folds_exclude_test(folds, splits["test"])
    for fold in folds:
        assert int(fold["val"][0] - fold["train"][-1]) >= WINDOW_BARS


def test_spearman_flags_a_channel_that_matches_a_label() -> None:
    """A channel copied from a label is reported and is not added to the tensor."""
    count = 40
    features = np.zeros((count, WINDOW_BARS, len(ENGINEERED_CHANNELS)), dtype=np.float32)
    signal = np.linspace(0.0, 1.0, count)
    features[:, -1, 0] = signal
    geometry = np.zeros((count, WINDOW_BARS, len(GEOMETRIC_CLASSES)), dtype=np.float32)
    geometry[:, -1, 0] = signal.astype(np.float32)
    state = np.zeros(count, dtype=np.int64)
    report = spearman_report(features, geometry, state, ENGINEERED_CHANNELS, flag_at=0.5)
    flagged = {
        (row["channel"], row["label"], row["reduction"])
        for row in report["flagged"]
    }
    assert (ENGINEERED_CHANNELS[0], GEOMETRIC_CLASSES[0], "last_bar") in flagged
    with pytest.raises(ValueError):
        spearman_report(features, geometry, state, ("hammer",))


def test_shap_aggregation_sums_each_bar_of_a_channel() -> None:
    """Window SHAP collapses onto channels without inventing a new feature."""
    values = np.zeros(WINDOW_BARS * len(ENGINEERED_CHANNELS), dtype=np.float64)
    values[0:: len(ENGINEERED_CHANNELS)] = 1.0
    summary = aggregate_shap_to_channels(
        values,
        n_time=WINDOW_BARS,
        n_channels=len(ENGINEERED_CHANNELS),
    )
    assert summary[0] == pytest.approx(float(WINDOW_BARS))
    assert summary[1] == pytest.approx(0.0)


def test_recognition_report_rejects_an_order_field() -> None:
    """A buy or expectancy field cannot pass the report guard."""
    assert_recognition_report({"spec_version": "recognition-15m-v1", "test": {}})
    with pytest.raises(ValueError):
        assert_recognition_report({"expectancy": 1.0})


def test_final_stride_stays_coarse_without_a_gpu() -> None:
    """CPU training does not materialize every overlapping window."""
    assert final_train_stride(60_000, len(ENGINEERED_CHANNELS)) == 4


def test_perturbation_indices_leave_a_future_bar() -> None:
    """Each causality probe has at least one bar after it."""
    indices = perturbation_indices(500, 47)
    assert indices == sorted(indices)
    assert indices[-1] < 499


def test_optuna_search_does_not_read_the_sealed_test() -> None:
    """One tiny trial fits only development folds."""
    optuna = pytest.importorskip("optuna")
    del optuna
    prepared = prepare_series(_walk(1400, seed=9))
    splits = prepared["splits"]
    study = run_optuna_search(
        prepared,
        splits["train"],
        splits["val"],
        n_trials=1,
        max_epochs=1,
        patience=1,
        hidden_choices=(8,),
        batch_choices=(16,),
        clip_choices=(5.0,),
        search_stride=8,
        seed=1,
    )
    folds = development_folds(splits["train"], splits["val"])
    assert_folds_exclude_test(folds, splits["test"])
    assert study["n_trials"] == 1
    assert study["trials"][0]["state"] == "COMPLETE"
    assert study["trials"][0]["value"] == pytest.approx(study["best_value"])
    assert "dilations" in study["best_params"]
    assert study["best_params"]["hidden"] == 8


def test_recognition_figures_cover_the_report(tmp_path: Path) -> None:
    """Each audit and the fit itself becomes a PNG."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)
    from research.recognition_15m.plots import write_recognition_figures

    paths = write_recognition_figures(_figure_report(), tmp_path)
    names = {path.name for path in paths}
    assert names == {
        "learning_curve.png",
        "validation_and_test.png",
        "optuna_trials.png",
        "label_correlation.png",
        "shap_channels.png",
        "calibration.png",
    }
    assert all(path.stat().st_size > 0 for path in paths)


def _figure_report() -> dict:
    """Small report with one flagged correlation and one SHAP class."""
    pairs = []
    for channel, label, spearman in (
        ("body_to_range", "doji", 0.9),
        ("volume_ratio", "doji", 0.1),
        ("body_to_range", "market_state", 0.2),
        ("volume_ratio", "market_state", -0.7),
    ):
        for reduction in ("last_bar", "window_mean"):
            pairs.append(
                {
                    "channel": channel,
                    "label": label,
                    "reduction": reduction,
                    "spearman": spearman,
                    "flagged": abs(spearman) >= 0.5,
                }
            )
    per_class = {
        "doji": {
            "precision": 0.5,
            "recall": 0.4,
            "f1": 0.44,
            "support": 3.0,
        }
    }
    split = {
        "geometry_macro_f1": 0.44,
        "geometry_per_class": {"doji": per_class["doji"]},
        "market_state": {"macro_f1": 0.3, "per_class": {}},
        "structure_tag": {"macro_f1": 0.2, "per_class": {}},
    }
    return {
        "fit": {
            "best_epoch": 1,
            "train_loss_by_epoch": [1.4, 0.9, 0.4],
            "val_loss_by_epoch": [1.3, 0.8, 1.0],
        },
        "val": split,
        "test": {
            **split,
            "geometry_macro_f1": 0.4,
            "geometry_calibration": {
                "expected_calibration_error": 0.05,
                "bins": [
                    {
                        "lower": 0.0,
                        "upper": 0.5,
                        "count": 8.0,
                        "confidence": 0.25,
                        "frequency": 0.3,
                    }
                ],
            },
        },
        "optuna": {
            "best_value": 0.5,
            "trials": [
                {"number": 0, "value": 0.2, "state": "COMPLETE"},
                {"number": 1, "value": None, "state": "PRUNED"},
                {"number": 2, "value": 0.5, "state": "COMPLETE"},
            ],
        },
        "correlation": {"threshold": 0.5, "pairs": pairs, "flagged": []},
        "shap": {
            "sample_size": 12,
            "per_class": {
                "doji": {
                    "skipped": False,
                    "channels": {"body_to_range": 0.4, "volume_ratio": 0.1},
                },
                "engulfing": {"skipped": True},
            },
        },
    }


def test_generated_notebook_is_a_recognition_runner() -> None:
    """The Colab notebook points at the search, correlation, and TreeSHAP."""
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "colab"
        / "smoke_test_recognition_15m_notebook.py"
    )
    spec = importlib.util.spec_from_file_location("recognition_notebook_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.validate_notebook()
