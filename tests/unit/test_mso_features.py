"""Unit tests for MSO structural features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_feature_extensions import build_mso_structural_features


def _minimal_v43(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "bb_width": rng.uniform(0.01, 0.05, n),
            "oi_zscore": rng.uniform(-1, 2, n),
            "oi_contracts": 1_000_000 + np.cumsum(rng.normal(0, 5000, n)),
            "funding_zscore": rng.uniform(-1, 1, n),
            "wick_asym": rng.uniform(-0.5, 0.5, n),
            "oi_price_divergence": rng.uniform(-0.01, 0.01, n),
        }
    )


def _ohlcv(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    spread = rng.uniform(0.5, 3.0, n)
    return pd.DataFrame(
        {
            "open": close - rng.uniform(0, 0.3, n),
            "high": close + spread,
            "low": close - spread,
            "close": close,
        }
    )


def test_oi_velocity_scale_invariant():
    n = 300
    df = _minimal_v43(n)
    ohlcv = _ohlcv(n)
    feat_a = build_mso_structural_features(df, df_ohlcv=ohlcv)
    df2 = df.copy()
    df2["oi_contracts"] = df2["oi_contracts"] * 2.0
    feat_b = build_mso_structural_features(df2, df_ohlcv=ohlcv)
    vel_a = feat_a["oi_velocity"].dropna()
    vel_b = feat_b["oi_velocity"].dropna()
    assert len(vel_a) > 50
    np.testing.assert_allclose(vel_a.values, vel_b.values, rtol=1e-5, atol=1e-8)


def test_oi_velocity_bounded():
    df = _minimal_v43(200)
    ohlcv = _ohlcv(200)
    feat = build_mso_structural_features(df, df_ohlcv=ohlcv)
    vel = feat["oi_velocity"].dropna()
    assert vel.abs().max() <= 0.05 + 1e-9
