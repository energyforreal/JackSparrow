"""Unit tests for MSO structural labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_labels import (
    MSO_STATE_DIMENSIONS,
    build_liquidity_condition_labels,
    build_momentum_quality_labels,
    build_mso_label,
    build_trend_regime_labels,
    build_vol_regime_labels,
    build_compression_expansion_labels,
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


def test_collapse_trend_regime_labels():
    from feature_store.jacksparrow_mso_labels import collapse_trend_regime_labels

    labels = pd.Series(["STRONG_BULL", "WEAK_BEAR", "RANGE"])
    collapsed = collapse_trend_regime_labels(labels)
    assert list(collapsed) == ["BULL", "BEAR", "RANGE"]


def test_classes_for_dimension_trend_3class():
    from feature_store.jacksparrow_mso_labels import classes_for_dimension

    assert classes_for_dimension("trend_regime", trend_3class=True) == ("BULL", "RANGE", "BEAR")
    assert len(classes_for_dimension("trend_regime", trend_3class=False)) == 5


def test_trend_uses_train_quantiles_at_t():
    n = 400
    df = _synthetic_feat(n)
    _, stats = build_trend_regime_labels(df, forward_bars=6, train_end_idx=200)
    assert stats["threshold_mode"] == "train_quantile_at_t"
    assert stats["adx_thr_strong"] > 0
    assert stats["adx_thr_weak"] > 0
    assert stats["labeled_fraction"] == 1.0


def test_trend_labels_at_t_multi_class():
    n = 600
    rng = np.random.default_rng(42)
    df = _synthetic_feat(n)
    df["adx_14"] = np.concatenate(
        [
            rng.uniform(12, 17, 200),
            rng.uniform(22, 26, 200),
            rng.uniform(30, 38, 200),
        ]
    )
    df["trend_mom"] = np.concatenate(
        [
            rng.uniform(-0.001, 0.001, 200),
            rng.uniform(0.0003, 0.001, 100),
            rng.uniform(-0.001, -0.0003, 100),
            rng.uniform(0.0008, 0.002, 100),
            rng.uniform(-0.002, -0.0008, 100),
        ]
    )
    labels, stats = build_trend_regime_labels(df, forward_bars=6, train_end_idx=480)
    counts = stats["class_counts"]
    non_range_classes = [k for k, v in counts.items() if k != "RANGE" and v >= 50]
    assert len(non_range_classes) >= 2
    assert stats["labeled_fraction"] == 1.0


def test_momentum_diverging_below_50pct():
    df = _synthetic_feat(2000)
    rng = np.random.default_rng(7)
    df["rsi_14"] = rng.uniform(25, 75, 2000)
    df["rsi_mom"] = rng.uniform(-1.5, 1.5, 2000)
    df["trend_mom"] = rng.uniform(-0.002, 0.002, 2000)
    df["oi_price_divergence"] = rng.uniform(-0.03, 0.03, 2000)
    labels, stats = build_momentum_quality_labels(df, forward_bars=6, train_end_idx=1600)
    top = max(stats["class_counts"], key=stats["class_counts"].get)
    top_frac = stats["class_counts"][top] / max(1, labels.notna().sum())
    assert top_frac < 0.55
    assert stats["threshold_mode"] == "train_quantile_at_t"


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


def test_vol_regime_uses_real_high_low():
    n = 250
    rng = np.random.default_rng(11)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 0.3, n)))
    spread = rng.uniform(2.0, 5.0, n)
    df_wide = pd.DataFrame(
        {
            "high": close + spread,
            "low": close - spread,
        }
    )
    df_narrow = pd.DataFrame({"high": close * 1.0001, "low": close * 0.9999})
    _, stats_wide = build_vol_regime_labels(df_wide, close, forward_bars=6)
    _, stats_narrow = build_vol_regime_labels(df_narrow, close, forward_bars=6)
    labeled_wide = sum(stats_wide["class_counts"].values())
    labeled_narrow = sum(stats_narrow["class_counts"].values())
    assert labeled_wide > 0 and labeled_narrow > 0
    assert stats_wide["class_counts"] != stats_narrow["class_counts"]


def test_momentum_else_assigns_healthy():
    n = 50
    df = _synthetic_feat(n)
    df["rsi_14"] = 55.0
    df["rsi_mom"] = 0.6
    df["trend_mom"] = 0.001
    df["oi_price_divergence"] = 0.0
    labels, _ = build_momentum_quality_labels(df, forward_bars=6)
    assert labels.iloc[0] == "HEALTHY"


def test_compression_post_expansion_exists():
    n = 300
    rng = np.random.default_rng(13)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 0.2, n)))
    spread = rng.uniform(0.5, 1.5, n)
    df = _synthetic_feat(n)
    df["high"] = close + spread
    df["low"] = close - spread
    df["bb_width"] = 0.02
    df.loc[100:150, "bb_width"] = 0.08
    df.loc[151:200, "bb_width"] = 0.015
    labels, stats = build_compression_expansion_labels(df, close, forward_bars=12)
    assert stats["class_counts"].get("POST_EXPANSION", 0) > 0 or stats["class_counts"].get(
        "PRE_EXPANSION", 0
    ) > 0
    assert stats["class_counts"].get("COMPRESSION", 0) < n


def test_vol_regime_multi_class_with_train_quantiles():
    n = 2000
    rng = np.random.default_rng(21)
    close = pd.Series(45000 + np.cumsum(rng.normal(0, 15, n)))
    high = close + rng.uniform(20, 120, n)
    low = close - rng.uniform(20, 120, n)
    df = pd.DataFrame({"high": high.values, "low": low.values})
    split = int(n * 0.8)
    _, stats = build_vol_regime_labels(df, close, forward_bars=2, train_end_idx=split)
    counts = stats["class_counts"]
    assert stats["threshold_mode"] == "train_quantile"
    assert sum(1 for v in counts.values() if v >= 50) >= 3
    assert counts.get("LOW_VOL", 0) > 0
    assert counts.get("EXPANDING_VOL", 0) > 0


def test_liquidity_train_quantiles_not_all_balanced():
    n = 2000
    rng = np.random.default_rng(22)
    close = pd.Series(45000 + np.cumsum(rng.normal(0, 15, n)))
    df = pd.DataFrame(
        {
            "oi_zscore": rng.normal(0.3, 0.5, n),
            "funding_zscore": rng.normal(0.1, 0.4, n),
            "wick_asym": rng.normal(0, 0.2, n),
            "oi_acceleration": rng.normal(0, 0.0015, n),
            "trend_mom": rng.normal(0, 0.00025, n),
        }
    )
    split = int(n * 0.8)
    labels, stats = build_liquidity_condition_labels(
        df, close, forward_bars=6, train_end_idx=split
    )
    balanced_frac = stats["class_counts"]["BALANCED"] / len(labels)
    assert balanced_frac < 0.95
    assert stats["threshold_mode"] == "train_quantile_adaptive"
