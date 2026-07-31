"""Unit tests for Colab transformer training helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd_15m.contract import CONTINUOUS_LABEL_COLS, FEATURE_COLS
from scripts.colab.transformer_training import (
    build_windows,
    fit_label_stats,
    fit_vol_regime_edges,
    split_purged_windows,
    standardize_labels,
    to_vol_regime,
)


def _synthetic_feat_df(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    data = {col: rng.normal(size=n) for col in FEATURE_COLS}
    for col in CONTINUOUS_LABEL_COLS:
        data[col] = rng.normal(size=n)
    return pd.DataFrame(data)


def test_build_windows_shape() -> None:
    feat_df = _synthetic_feat_df(300)
    x, y = build_windows(feat_df, FEATURE_COLS, CONTINUOUS_LABEL_COLS, window_len=64, stride=8)
    assert x.shape[1:] == (64, len(FEATURE_COLS))
    assert y.shape[1] == len(CONTINUOUS_LABEL_COLS)
    assert len(x) == len(y)
    assert len(x) > 0


def test_split_purged_windows_reserves_test() -> None:
    n = 100
    x_all = np.zeros((n, 8, 4), dtype=np.float32)
    y_all = np.zeros((n, len(CONTINUOUS_LABEL_COLS)), dtype=np.float64)
    train_frac, val_frac, embargo = 0.65, 0.15, 2
    splits = split_purged_windows(
        x_all,
        y_all,
        train_frac=train_frac,
        val_frac=val_frac,
        embargo_bars=embargo,
    )
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    assert len(splits["x_train"]) == train_end
    assert len(splits["x_val"]) == val_end - train_end - embargo
    assert len(splits["x_test"]) == n - val_end - embargo


def test_standardize_labels_masks_nan() -> None:
    y = np.array([[1.0, np.nan], [2.0, 3.0]], dtype=np.float64)
    mean, std = fit_label_stats(y)
    yz, mask = standardize_labels(y, mean, std)
    assert mask[0, 1] == 0.0
    assert mask[1, 1] == 1.0
    assert yz[0, 1] == 0.0


def test_vol_regime_four_classes() -> None:
    n = 20
    y = np.zeros((n, len(CONTINUOUS_LABEL_COLS)))
    fv_idx = CONTINUOUS_LABEL_COLS.index("future_volatility")
    y[:, fv_idx] = np.linspace(0, 1, n)
    edges = fit_vol_regime_edges(y, [0.25, 0.5, 0.75])
    regimes = to_vol_regime(y, edges)
    assert regimes.min() >= 0
    assert regimes.max() <= 3
