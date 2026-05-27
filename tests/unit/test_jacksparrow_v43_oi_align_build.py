"""Integration: OI ticker frame alignment produces non-flat OI features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix
from feature_store.jacksparrow_v43_oi_history import oi_candles_to_ticker_frame


def test_build_matrix_oi_features_nonzero_when_oi_aligned() -> None:
    n = 200
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(42)
    close = 50000.0 + np.cumsum(rng.normal(0, 10, n))
    df_5m = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 50,
            "low": close - 50,
            "close": close,
            "volume": rng.uniform(1, 10, n),
        }
    )
    oi_level = 1000.0 + np.cumsum(rng.normal(0, 5, n))
    df_oi_raw = pd.DataFrame({"timestamp": ts, "close": oi_level})
    df_oi = oi_candles_to_ticker_frame(df_oi_raw, df_spot=df_5m, align_to=df_5m)
    df_funding = pd.DataFrame({"timestamp": ts, "funding_rate": 0.0001})

    feat = build_v43_feature_matrix(
        df_5m,
        None,
        None,
        df_funding,
        df_oi=df_oi,
        for_training=True,
    )
    assert len(feat) == n
    assert float(feat["oi_zscore"].std()) > 1e-6
    assert float(feat["oi_change_6"].std()) > 1e-8
