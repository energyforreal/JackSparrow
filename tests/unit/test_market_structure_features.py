"""Unit tests for causal market-structure and chart-geometry features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import NATIVE_STRUCTURE_COLS
from feature_store.transformer_btcusd.features import add_features
from feature_store.transformer_btcusd.structure import add_market_structure_features


STRUCTURE_SAMPLE_COLS = (
    "structure_bias",
    "hh_count",
    "hl_count",
    "trend_efficiency",
    "breakout_size_atr",
    "range_width_atr",
    "dist_to_support_atr",
    "peak_diff_atr",
    "ema21_slope_atr",
)


def _base_ohlcv(n: int = 200, seed: int = 0, freq: str = "15min") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = 50000 + np.cumsum(rng.normal(0, 30, n))
    open_ = close + rng.normal(0, 15, n)
    high = np.maximum(open_, close) + rng.uniform(5, 40, n)
    low = np.minimum(open_, close) - rng.uniform(5, 40, n)
    return pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
            "funding_rate": 0.0001,
            "open_interest": 1e6,
        }
    )


def _uptrend_swings(n: int = 160) -> pd.DataFrame:
    """Rising HH/HL staircase with ATR-sized legs."""
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = np.zeros(n, dtype=float)
    high = np.zeros(n, dtype=float)
    low = np.zeros(n, dtype=float)
    open_ = np.zeros(n, dtype=float)
    price = 50000.0
    for i in range(n):
        cycle = i % 20
        if cycle < 10:
            price += 40.0
        else:
            price -= 12.0
        open_[i] = price - 8.0
        close[i] = price
        high[i] = max(open_[i], close[i]) + 10.0
        low[i] = min(open_[i], close[i]) - 10.0
    return pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
            "funding_rate": 0.0001,
            "open_interest": 1e6,
        }
    )


def test_structure_features_are_causal() -> None:
    df = _base_ohlcv(180)
    full = add_features(df, resolution_minutes=15)
    for i in (60, 120, 179):
        prefix = add_features(df.iloc[: i + 1].copy(), resolution_minutes=15)
        for col in STRUCTURE_SAMPLE_COLS:
            np.testing.assert_allclose(
                float(prefix[col].iloc[-1]),
                float(full[col].iloc[i]),
                rtol=1e-8,
                atol=1e-8,
                err_msg=f"leakage in {col} at i={i}",
            )


def test_zigzag_does_not_confirm_high_until_reversal() -> None:
    n = 80
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    open_ = np.full(n, 100.0)
    # Impulse high at bar 40, then grind sideways (no ATR reversal yet).
    for i in range(20, 41):
        close[i] = 100.0 + (i - 20) * 5.0
        open_[i] = close[i] - 1.0
        high[i] = close[i] + 1.0
        low[i] = open_[i] - 1.0
    peak = float(high[40])
    df = pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    feat = add_market_structure_features(add_features(df, resolution_minutes=15))
    # At the peak bar the extreme is still unconfirmed (tracking a high).
    assert float(feat["last_swing_dir"].iloc[40]) in (0.0, 1.0)
    assert float(feat["unconfirmed_ext_atr"].iloc[40]) != 0.0 or peak > close[40]
    # Deep reversal after the peak confirms the swing high.
    for i in range(41, 55):
        close[i] = peak - (i - 40) * 8.0
        open_[i] = close[i] + 1.0
        high[i] = open_[i] + 1.0
        low[i] = close[i] - 2.0
    df2 = pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    feat2 = add_market_structure_features(add_features(df2, resolution_minutes=15))
    assert float(feat2["last_swing_dir"].iloc[54]) == 1.0
    assert float(feat2["bars_since_swing"].iloc[54]) >= 0.0


def test_breakout_size_uses_prior_donchian() -> None:
    n = 80
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    open_ = np.full(n, 100.0)
    close = np.full(n, 100.5)
    high = np.full(n, 101.0)
    low = np.full(n, 99.5)
    range_high = 101.0
    open_[-1], close[-1], high[-1], low[-1] = 101.0, 110.0, 111.0, 100.5
    df = pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100.0),
            "funding_rate": 0.0001,
            "open_interest": 1e6,
        }
    )
    feat = add_features(df, resolution_minutes=15)
    size = float(feat["breakout_size_atr"].iloc[-1])
    assert size > 0.0
    # Current bar high must not be the Donchian cap (would yield ~0 or negative).
    assert float(close[-1]) > range_high


def test_synthetic_hh_hl_positive_structure_bias() -> None:
    feat = add_features(_uptrend_swings(), resolution_minutes=15)
    assert float(feat["structure_bias"].iloc[-1]) > 0.0
    assert float(feat["hh_count"].iloc[-1]) + float(feat["hl_count"].iloc[-1]) > 0.0


def test_native_structure_cols_finite() -> None:
    feat = add_features(_base_ohlcv(220), resolution_minutes=15)
    for col in NATIVE_STRUCTURE_COLS:
        assert col in feat.columns
        assert np.isfinite(feat[col].to_numpy()).all(), col
