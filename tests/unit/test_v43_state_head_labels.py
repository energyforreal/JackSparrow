"""Unit tests for v43 state-head label builders."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.jacksparrow_v43_labels import (
    V43_REGIME_CLASSES,
    build_regime_labels,
    build_trade_quality_labels,
    build_triple_barrier_labels,
    build_vol_expansion_labels,
)


def _synthetic_feat(n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "adx_14": rng.uniform(10, 40, n),
            "hurst_60": rng.uniform(0.4, 0.7, n),
            "trend_mom": rng.normal(0, 0.01, n),
            "vol_regime": rng.uniform(0, 1, n),
            "atr_pct": rng.uniform(0.001, 0.02, n),
        }
    )


def test_build_regime_labels_returns_four_classes():
    df = _synthetic_feat()
    labels, stats = build_regime_labels(df, n_bars=3)
    assert isinstance(stats["class_counts"], dict)
    labeled = labels.dropna()
    assert labeled.isin(V43_REGIME_CLASSES).all()


def test_build_vol_expansion_labels_binary():
    n = 400
    close = pd.Series(np.cumprod(1 + np.random.default_rng(1).normal(0, 0.002, n)))
    labels, stats = build_vol_expansion_labels(close, forward_bars=12)
    valid = labels.dropna()
    assert set(valid.unique()).issubset({0.0, 1.0})
    assert stats["labeled_fraction"] > 0


def test_align_close_to_feature_matrix_by_timestamp():
    from feature_store.jacksparrow_v43_train_multihead import align_close_to_feature_matrix

    n = 600
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = pd.Series(np.linspace(100.0, 110.0, n), index=ts)
    df = _synthetic_feat(n)
    df["timestamp"] = ts
    aligned = align_close_to_feature_matrix(df, close)
    assert int(aligned.notna().sum()) == n
    labels, stats = build_vol_expansion_labels(aligned, forward_bars=12)
    assert stats["labeled_fraction"] > 0.1


def test_build_trade_quality_labels_excludes_timeout():
    n = 300
    rng = np.random.default_rng(2)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.003, n)))
    labels, stats = build_trade_quality_labels(
        close, forward_bars=6, take_profit_pct=0.02, stop_loss_pct=0.02
    )
    valid = labels.dropna()
    assert set(valid.unique()).issubset({0.0, 1.0})
    tb, _ = build_triple_barrier_labels(
        close, forward_bars=6, take_profit_pct=0.02, stop_loss_pct=0.02
    )
    timeouts = int((tb == 0).sum())
    assert stats["timeout_fraction"] >= 0
    assert len(valid) <= int(tb.notna().sum() - timeouts + 1)
