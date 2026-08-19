"""Tests for per-TF BTCUSD transformer feature pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    CONTINUOUS_LABEL_COLS,
    FEATURE_COLS,
    RESOLUTION_MINUTES,
    SUPPORTED_RESOLUTIONS,
    max_label_horizon_bars,
)
from feature_store.transformer_btcusd.features import add_features, build_feature_matrix
from feature_store.transformer_btcusd.inference import (
    build_candle_class_window,
    build_inference_window,
    unstandardize_continuous,
)
from feature_store.transformer_btcusd.labels import compute_market_labels, trim_label_tail


def _synthetic_ohlcv(n: int = 300, *, freq: str = "15min") -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = 50000 + np.cumsum(np.random.default_rng(42).normal(0, 20, n))
    return pd.DataFrame(
        {
            "time": ts,
            "open": close - 5,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": np.full(n, 100.0),
            "funding_rate": np.linspace(0.0001, 0.0002, n),
            "open_interest": np.linspace(1e6, 1.1e6, n),
        }
    )


def _bars_needed(resolution: str) -> int:
    minutes = RESOLUTION_MINUTES[resolution]
    # Enough rows after dropna for 128-window inference with scaled lookbacks.
    scaled_long = max(1, int(round(96 * minutes / 5)))
    return max(400, scaled_long + 150)


def _freq_for_resolution(resolution: str) -> str:
    return {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h"}[resolution]


@pytest.mark.parametrize("resolution", SUPPORTED_RESOLUTIONS)
def test_add_features_produces_all_feature_cols(resolution: str) -> None:
    minutes = RESOLUTION_MINUTES[resolution]
    n = _bars_needed(resolution)
    feat_df = build_feature_matrix(
        _synthetic_ohlcv(n, freq=_freq_for_resolution(resolution)),
        resolution_minutes=minutes,
        dropna=True,
    )
    for col in FEATURE_COLS:
        assert col in feat_df.columns
    assert "candle_class_id" in feat_df.columns
    assert ((feat_df["candle_class_id"] >= 0) & (feat_df["candle_class_id"] <= 12)).all()
    assert len(feat_df) >= 128


@pytest.mark.parametrize("resolution", SUPPORTED_RESOLUTIONS)
def test_build_inference_window_shape(resolution: str) -> None:
    minutes = RESOLUTION_MINUTES[resolution]
    n = _bars_needed(resolution)
    feat_df = build_feature_matrix(
        _synthetic_ohlcv(n, freq=_freq_for_resolution(resolution)),
        resolution_minutes=minutes,
        dropna=True,
    )
    values = feat_df[list(FEATURE_COLS)].values.astype(np.float32)
    window = build_inference_window(values, window_len=128)
    assert window.shape == (1, 128, len(FEATURE_COLS))
    assert np.isfinite(window).all()
    cat = build_candle_class_window(feat_df["candle_class_id"].values, window_len=128)
    assert cat.shape == (1, 128)
    assert cat.dtype == np.int64
    assert ((cat >= 0) & (cat <= 12)).all()


def test_path_labels_trim_tail() -> None:
    n = _bars_needed("15m")
    raw = _synthetic_ohlcv(n, freq="15min")
    feat = add_features(raw, resolution_minutes=15).dropna().reset_index(drop=True)
    labeled = compute_market_labels(
        feat,
        path_label_horizon_bars=8,
        mae_floor_atr_mult=0.25,
    )
    trimmed = trim_label_tail(labeled, path_label_horizon_bars=8)
    max_h = max_label_horizon_bars(8)
    assert len(trimmed) == len(labeled) - (max_h + 1)
    assert trimmed.loc[50, "mfe"] >= 0.0
    assert trimmed.loc[50, "mae"] >= 0.0


def test_unstandardize_continuous_roundtrip() -> None:
    mean = np.zeros(len(CONTINUOUS_LABEL_COLS))
    std = np.ones(len(CONTINUOUS_LABEL_COLS))
    z = np.random.default_rng(0).normal(size=len(CONTINUOUS_LABEL_COLS))
    out = unstandardize_continuous(z, mean, std)
    assert set(out.keys()) == set(CONTINUOUS_LABEL_COLS)
    assert out["mfe"] == pytest.approx(float(z[0]))
