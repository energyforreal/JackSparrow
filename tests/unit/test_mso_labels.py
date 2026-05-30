"""Unit tests for MSO structural labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_labels import (
    MSO_STATE_DIMENSIONS,
    build_liquidity_condition_labels,
    build_mso_label,
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
