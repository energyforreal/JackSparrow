"""Unit tests for last-bar direction-predictability helpers."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    V14_FEATURE_GROUPS,
    fusion_feature_cols_v14,
)
from scripts.colab.direction_predictability import (
    CHANCE_BALANCED_ACC,
    PREREGISTERED_READINGS,
    VOL_TIME_COLS,
    ablation_table,
    balanced_acc_ci,
    bear_vs_bull_auc,
    ci_includes,
    classify_reading,
    classify_transformer_juice,
    confusion_matrix,
    finite_feature_mask,
    group_column_mask,
    map_times_to_rows,
    neutral_vs_rest_auc,
    per_class_recall,
    run_direction_predictability,
    softmax_rows,
    train_only_zscore,
)
from scripts.colab.fusion_diagnostics import last_bar_matrix


def test_preregistered_readings_are_documented() -> None:
    assert set(PREREGISTERED_READINGS) == {
        "no_direction",
        "magnitude_not_side",
        "real_side_signal",
        "transformer_left_juice",
    }


def test_bootstrap_ci_covers_chance_on_constant_neutral() -> None:
    y = np.tile(np.array([0, 1, 2], dtype=np.int64), 400)
    pred = np.full(y.shape, 1, dtype=np.int64)
    lo, hi = balanced_acc_ci(y, pred, block_len=12, seed=0)
    assert ci_includes(lo, hi, CHANCE_BALANCED_ACC)
    assert lo is not None and hi is not None
    assert hi - lo < 0.05


def test_neutral_vs_rest_splits_from_bear_bull_on_vol_labels() -> None:
    n = 600
    rv = np.linspace(0.0, 1.0, n)
    y = np.where(rv > 0.55, 1, np.where(np.arange(n) % 2 == 0, 0, 2)).astype(np.int64)
    proba = np.zeros((n, 3), dtype=np.float64)
    proba[:, 1] = rv
    proba[:, 0] = (1.0 - rv) * 0.5
    proba[:, 2] = (1.0 - rv) * 0.5
    nvr = neutral_vs_rest_auc(y, proba)
    bvb = bear_vs_bull_auc(y, proba)
    assert nvr is not None and nvr > 0.85
    assert bvb is not None
    assert abs(float(bvb) - 0.5) < 0.08
    row = {
        "balanced_acc_ci": [0.34, 0.40],
        "neutral_vs_rest_auc_ci": [0.80, 0.95],
        "bear_vs_bull_auc_ci": [0.46, 0.54],
        "log_loss_beats_prior": False,
    }
    assert classify_reading(row) == "magnitude_not_side"


def test_classify_reading_tokens() -> None:
    assert (
        classify_reading(
            {
                "balanced_acc_ci": [0.30, 0.36],
                "neutral_vs_rest_auc_ci": [0.48, 0.52],
                "bear_vs_bull_auc_ci": [0.47, 0.53],
                "log_loss_beats_prior": False,
            }
        )
        == "no_direction"
    )
    assert (
        classify_reading(
            {
                "balanced_acc_ci": [0.40, 0.52],
                "neutral_vs_rest_auc_ci": [0.48, 0.56],
                "bear_vs_bull_auc_ci": [0.58, 0.72],
                "log_loss_beats_prior": True,
            }
        )
        == "real_side_signal"
    )


def test_transformer_juice_requires_side_gap_and_not_dump() -> None:
    last_bar = {
        "bear_vs_bull_auc": 0.62,
        "bear_vs_bull_auc_ci": [0.58, 0.70],
    }
    transformer = {"bear_vs_bull_auc": 0.50, "neutral_dump": False}
    assert classify_transformer_juice(last_bar, transformer) is True
    dump = {"bear_vs_bull_auc": 0.50, "neutral_dump": True}
    assert classify_transformer_juice(last_bar, dump) is False
    close = {
        "bear_vs_bull_auc": 0.51,
        "bear_vs_bull_auc_ci": [0.49, 0.54],
    }
    assert classify_transformer_juice(close, transformer) is False


def test_ablation_knockout_and_add_one_in_shapes() -> None:
    rng = np.random.default_rng(1)
    names = list(fusion_feature_cols_v14())
    n = 90
    x = rng.normal(size=(n, len(names)))
    rv_i = names.index("rv_16")
    x[:, rv_i] = np.linspace(-2.0, 2.0, n)
    y = np.where(x[:, rv_i] > 0.4, 1, np.where(x[:, rv_i] < -0.4, 0, 2)).astype(
        np.int64
    )
    ret = rng.normal(size=n)
    train_idx = np.arange(0, 60)
    val_idx = np.arange(60, 90)
    table = ablation_table(
        "logistic",
        x,
        y,
        ret,
        names,
        train_idx,
        val_idx,
        seed=0,
        block_len=12,
    )
    assert set(table["knockout"]) <= set(V14_FEATURE_GROUPS)
    assert set(table["add_one_in"]) <= set(V14_FEATURE_GROUPS)
    assert "vol_time_null" in table
    assert table["vol_time_null"].get("ok") is True
    vol_mask = group_column_mask(names, VOL_TIME_COLS)
    assert int(vol_mask.sum()) == len(VOL_TIME_COLS)


def test_map_times_to_rows_stride_join() -> None:
    labeled = pd.date_range("2024-01-01", periods=40, freq="5min", tz="UTC")
    query = labeled[::4]
    pos = map_times_to_rows(labeled.to_numpy(), query.to_numpy())
    assert pos.tolist() == list(range(0, 40, 4))
    missing = map_times_to_rows(
        labeled.to_numpy(),
        pd.DatetimeIndex(["1999-01-01"], tz="UTC").to_numpy(),
    )
    assert missing.tolist() == [-1]


def test_train_only_zscore_uses_train_stats() -> None:
    train = np.array([[0.0, 10.0], [2.0, 30.0], [4.0, 50.0]], dtype=np.float64)
    eval_x = np.array([[6.0, 70.0], [8.0, 90.0]], dtype=np.float64)
    z_tr, z_ev = train_only_zscore(train, eval_x)
    assert z_tr.mean(axis=0) == pytest.approx(0.0, abs=1e-12)
    assert z_ev[0, 0] > z_tr[-1, 0]


def test_finite_feature_mask_and_raw_last_bar() -> None:
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=4, freq="5min", tz="UTC"),
            "ret_1": [0.1, np.nan, 0.2, 0.3],
        }
    )
    raw, names = last_bar_matrix(frame, cols=("ret_1",), fill_nonfinite=False)
    assert "ret_1" in names
    mask = finite_feature_mask(raw)
    assert mask.tolist() == [True, False, True, True]
    filled, _ = last_bar_matrix(frame, cols=("ret_1",), fill_nonfinite=True)
    assert np.isfinite(filled).all()
    mixed = np.column_stack(
        [np.array([1.0, 2.0, 3.0]), np.array([np.nan, np.nan, np.nan])]
    )
    assert finite_feature_mask(mixed).tolist() == [True, True, True]


def test_confusion_and_softmax_helpers() -> None:
    y = np.array([0, 1, 2, 1])
    pred = np.array([0, 1, 1, 1])
    mat = confusion_matrix(y, pred)
    assert mat.shape == (3, 3)
    assert mat[1, 1] == 2
    rec = per_class_recall(mat)
    assert rec["NEUTRAL"] == pytest.approx(1.0)
    logits = np.array([[10.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    proba = softmax_rows(logits)
    assert proba[0, 0] == pytest.approx(1.0, abs=1e-4)
    assert proba[1].sum() == pytest.approx(1.0)


def test_run_direction_predictability_does_not_encode_branch() -> None:
    src = inspect.getsource(run_direction_predictability)
    assert "stop_target_or_features" not in src
    assert "decide_branch" not in src
    rng = np.random.default_rng(2)
    names = list(fusion_feature_cols_v14())
    n = 220
    x = rng.normal(size=(n, len(names)))
    y = np.tile(np.array([0, 1, 2], dtype=np.int64), n // 3 + 3)[:n]
    y = np.stack([y, y, y, y], axis=1)
    ret = rng.normal(size=(n, 4))
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC").to_numpy()
    report = run_direction_predictability(
        x,
        names,
        y,
        ret,
        times,
        seed=0,
        score_test=True,
        ablate_groups=False,
        class_weight_sensitivity=False,
    )
    assert "preregistered_readings" in report
    assert "horizons" in report
    first = next(iter(report["horizons"].values()))
    assert first.get("discovery_reading") in PREREGISTERED_READINGS or first.get(
        "ok"
    ) is False
    assert "branch" not in report
