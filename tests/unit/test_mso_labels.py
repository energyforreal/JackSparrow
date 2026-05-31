"""Unit tests for MSO structural labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_labels import (
    MSO_STATE_DIMENSIONS,
    build_liquidity_condition_labels,
    build_mso_label,
    build_trend_regime_labels,
    classes_for_dimension,
)


def _synthetic_feat(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "adx_14": rng.uniform(15, 35, n),
            "trend_mom": rng.uniform(-0.002, 0.002, n),
            "hurst_60": rng.uniform(0.4, 0.7, n),
            "atr_pct": rng.uniform(0.001, 0.01, n),
            "vol_regime": rng.uniform(0.5, 1.5, n),
            "bb_width": rng.uniform(0.01, 0.05, n),
            "oi_zscore": rng.uniform(-1, 2, n),
            "funding_zscore": rng.uniform(-1, 1, n),
            "wick_asym": rng.uniform(-0.5, 0.5, n),
            "oi_acceleration": rng.uniform(-0.01, 0.01, n),
            "oi_price_divergence": rng.uniform(-0.01, 0.01, n),
            "rsi_14": rng.uniform(30, 70, n),
            "rsi_mom": rng.uniform(-2, 2, n),
        }
    )


def test_mso_state_dimensions_count():
    assert len(MSO_STATE_DIMENSIONS) == 6


def test_liquidity_labels_balanced_class_exists():
    df = _synthetic_feat(200)
    close = pd.Series(np.linspace(100, 101, 200))
    labels, stats = build_liquidity_condition_labels(df, close, forward_bars=6)
    assert "BALANCED" in stats["class_counts"]
    assert labels.notna().all()


def test_build_mso_label_dispatch():
    df = _synthetic_feat(300)
    close = pd.Series(np.linspace(100, 102, 300))
    for dim in MSO_STATE_DIMENSIONS:
        labels, _ = build_mso_label(df, close, dim, 6)
        assert len(classes_for_dimension(dim)) >= 4


def test_trend_uses_fixed_adx_thresholds():
    n = 400
    df = _synthetic_feat(n)
    _, stats = build_trend_regime_labels(df, forward_bars=6, train_end_idx=200)
    assert stats["threshold_mode"] == "fixed"
    assert stats["adx_thr_strong"] == 28.0
    assert stats["adx_thr_weak"] == 20.0


def test_trend_labels_multi_class_on_varied_adx():
    n = 500
    df = _synthetic_feat(n)
    df["adx_14"] = np.concatenate(
        [np.full(100, 15.0), np.full(150, 25.0), np.full(150, 32.0), np.full(100, 18.0)]
    )
    df["trend_mom"] = np.concatenate(
        [np.full(100, -0.001), np.full(150, 0.0006), np.full(150, -0.0012), np.full(100, 0.0002)]
    )
    labels, stats = build_trend_regime_labels(df, forward_bars=6)
    counts = stats["class_counts"]
    non_range = sum(v for k, v in counts.items() if k != "RANGE")
    assert non_range > 50
    assert len([k for k, v in counts.items() if v >= 50 and k != "RANGE"]) >= 2


def test_momentum_not_single_class_dominant():
    from feature_store.jacksparrow_mso_labels import build_momentum_quality_labels

    df = _synthetic_feat(600)
    rng = np.random.default_rng(7)
    df["rsi_14"] = rng.uniform(25, 75, 600)
    df["rsi_mom"] = rng.uniform(-1.5, 1.5, 600)
    df["trend_mom"] = rng.uniform(-0.002, 0.002, 600)
    df["oi_price_divergence"] = rng.uniform(-0.03, 0.03, 600)
    labels, stats = build_momentum_quality_labels(df, forward_bars=6)
    top = max(stats["class_counts"], key=stats["class_counts"].get)
    top_frac = stats["class_counts"][top] / max(1, labels.notna().sum())
    assert top_frac < 0.95


def test_liquidity_not_all_balanced():
    df = _synthetic_feat(400)
    rng = np.random.default_rng(9)
    df["oi_zscore"] = rng.uniform(0, 3, 400)
    df["funding_zscore"] = rng.uniform(-2, 2, 400)
    df["wick_asym"] = rng.uniform(-0.8, 0.8, 400)
    df["oi_acceleration"] = rng.uniform(-0.02, 0.02, 400)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 0.5, 400)))
    labels, stats = build_liquidity_condition_labels(df, close, forward_bars=6)
    balanced_frac = stats["class_counts"]["BALANCED"] / len(labels)
    assert balanced_frac < 0.95
    assert stats["class_counts"]["BALANCED"] > 0
