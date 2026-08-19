"""Unit tests for causal Tier-1 candle structure features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.features import (
    add_candle_structure_features,
    add_features,
    build_feature_matrix,
)

STRUCTURE_COLS = (
    "close_loc",
    "range_atr",
    "body_atr",
    "gap_atr",
    "inside_bar",
    "outside_bar",
    "engulf_score",
)


def _base_ohlcv(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
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


def test_flat_bar_close_loc_and_range_atr() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    df.loc[df.index[-1], ["open", "high", "low", "close"]] = [px, px, px, px]
    feat = add_features(df, resolution_minutes=5)
    assert float(feat["close_loc"].iloc[-1]) == 0.5
    assert float(feat["range_atr"].iloc[-1]) < 1e-3


def test_bullish_engulfing_score() -> None:
    n = 80
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    open_ = np.full(n, 100.0)
    close = np.full(n, 101.0)
    high = np.full(n, 102.0)
    low = np.full(n, 99.0)
    # Prior bar bearish body 100 -> 90; current bullish 89 -> 102 (engulfs).
    open_[-2], close[-2], high[-2], low[-2] = 100.0, 90.0, 101.0, 89.0
    open_[-1], close[-1], high[-1], low[-1] = 88.0, 112.0, 113.0, 87.0
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
    feat = add_features(df, resolution_minutes=5)
    score = float(feat["engulf_score"].iloc[-1])
    assert score > 1.0


def test_inside_bar_not_outside() -> None:
    n = 80
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    open_ = np.full(n, 100.0)
    close = np.full(n, 101.0)
    high = np.full(n, 110.0)
    low = np.full(n, 90.0)
    open_[-2], close[-2], high[-2], low[-2] = 100.0, 105.0, 120.0, 80.0
    open_[-1], close[-1], high[-1], low[-1] = 100.0, 102.0, 110.0, 90.0
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
    feat = add_features(df, resolution_minutes=5)
    assert float(feat["inside_bar"].iloc[-1]) == 1.0
    assert float(feat["outside_bar"].iloc[-1]) == 0.0


def test_structure_features_are_causal() -> None:
    df = _base_ohlcv(120)
    full = add_features(df, resolution_minutes=5)
    for i in (40, 80, 119):
        prefix = add_features(df.iloc[: i + 1].copy(), resolution_minutes=5)
        for col in STRUCTURE_COLS:
            np.testing.assert_allclose(
                float(prefix[col].iloc[-1]),
                float(full[col].iloc[i]),
                rtol=1e-9,
                atol=1e-9,
                err_msg=f"leakage in {col} at i={i}",
            )


def test_structure_cols_finite_after_dropna() -> None:
    feat = build_feature_matrix(_base_ohlcv(400), resolution_minutes=5, dropna=True)
    for col in STRUCTURE_COLS:
        assert col in feat.columns
        assert np.isfinite(feat[col].to_numpy()).all()


def test_add_candle_structure_features_first_bar_zero_shifts() -> None:
    df = _base_ohlcv(40)
    feat = add_features(df, resolution_minutes=5)
    structured = add_candle_structure_features(feat.copy())
    assert float(structured["inside_bar"].iloc[0]) == 0.0
    assert float(structured["outside_bar"].iloc[0]) == 0.0
    assert float(structured["engulf_score"].iloc[0]) == 0.0
    assert float(structured["gap_atr"].iloc[0]) == 0.0
