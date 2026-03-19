"""Unit tests for CandlestickPatternEngine."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from feature_store.pattern_features.candlestick_patterns import (
    CandlestickPatternEngine,
    CANDLESTICK_FEATURES,
)


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    np.random.seed(42)
    base = 50000
    ret = np.random.randn(n).cumsum() * 0.002
    close = base * (1 + ret)
    high = close * (1 + np.abs(np.random.randn(n) * 0.005))
    low = close * (1 - np.abs(np.random.randn(n) * 0.005))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.random.randint(100, 1000, n).astype(float),
    })


def test_compute_all_returns_dataframe():
    """compute_all returns DataFrame with expected columns."""
    df = _make_ohlcv(100)
    engine = CandlestickPatternEngine()
    out = engine.compute_all(df)

    assert isinstance(out, pd.DataFrame)
    assert len(out) == len(df)
    for name in CANDLESTICK_FEATURES:
        assert name in out.columns, f"Missing column: {name}"


def test_compute_all_no_nan():
    """Output has no NaN after fillna(0)."""
    df = _make_ohlcv(100)
    engine = CandlestickPatternEngine()
    out = engine.compute_all(df)
    assert not out.isna().any().any()


def test_binary_patterns_in_range():
    """Binary pattern columns are 0 or 1."""
    df = _make_ohlcv(100)
    engine = CandlestickPatternEngine()
    out = engine.compute_all(df)

    binary_cols = [
        "cdl_doji", "cdl_hammer", "cdl_bull_engulfing", "cdl_morning_star"
    ]
    for col in binary_cols:
        if col in out.columns:
            assert out[col].isin([0, 1]).all(), f"{col} has values outside {0, 1}"
