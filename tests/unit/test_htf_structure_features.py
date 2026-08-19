"""Tests for closed-bar higher-timeframe structure merge on 5m."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    FEATURE_COLS,
    HTF_STRUCTURE_COLS,
    feature_cols_for_resolution,
)
from feature_store.transformer_btcusd.features import add_features


def _ohlcv(n: int, freq: str = "5min", seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = 50000 + np.cumsum(rng.normal(0, 15, n))
    return pd.DataFrame(
        {
            "time": ts,
            "open": close - 4,
            "high": close + 12,
            "low": close - 12,
            "close": close,
            "volume": np.full(n, 100.0),
            "funding_rate": 0.0001,
            "open_interest": 1e6,
        }
    )


def test_feature_cols_for_resolution_htf_only_on_5m() -> None:
    five = feature_cols_for_resolution("5m")
    fifteen = feature_cols_for_resolution("15m")
    assert fifteen == FEATURE_COLS
    assert five == FEATURE_COLS + HTF_STRUCTURE_COLS
    assert "htf_1h_structure_bias" in five
    assert "htf_1h_structure_bias" not in fifteen


def test_5m_has_htf_cols_15m_does_not() -> None:
    feat_5m = add_features(_ohlcv(900), resolution_minutes=5)
    feat_15m = add_features(_ohlcv(400, freq="15min"), resolution_minutes=15)
    for col in HTF_STRUCTURE_COLS:
        assert col in feat_5m.columns
        assert col not in feat_15m.columns
        assert np.isfinite(feat_5m[col].to_numpy()).all()


def test_htf_1h_ignores_unclosed_hour() -> None:
    n = 12 * 10 + 7
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 50000.0)
    high = close + 10.0
    low = close - 10.0
    # 10:00 is bar 120. Spike only in the forming 11:00 hour (10:05+).
    hour_close_idx = 12 * 10
    close[hour_close_idx + 1 :] = 55000.0
    high[hour_close_idx + 1 :] = 55100.0
    low[hour_close_idx + 1 :] = 54900.0
    df = pd.DataFrame(
        {
            "time": ts,
            "open": close - 5.0,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    full = add_features(df, resolution_minutes=5)
    forming_idx = n - 1
    np.testing.assert_allclose(
        float(full["htf_1h_range_width_atr"].iloc[forming_idx]),
        float(full["htf_1h_range_width_atr"].iloc[hour_close_idx]),
        rtol=1e-8,
        atol=1e-8,
    )


def test_htf_1h_structure_bias_is_causal() -> None:
    df = _ohlcv(960)
    full = add_features(df, resolution_minutes=5)
    for i in (400, 700, 959):
        prefix = add_features(df.iloc[: i + 1].copy(), resolution_minutes=5)
        np.testing.assert_allclose(
            float(prefix["htf_1h_structure_bias"].iloc[-1]),
            float(full["htf_1h_structure_bias"].iloc[i]),
            rtol=1e-8,
            atol=1e-8,
            err_msg=f"HTF leakage at i={i}",
        )
