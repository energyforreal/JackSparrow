"""Unit tests for CandlestickPatternEngine."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

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


def _trend_then_shape(
    *,
    n_trend: int,
    trend_step: float,
    shape: str,
    start: float = 50000.0,
) -> pd.DataFrame:
    """Build monotonic trend bars then one classic hammer / inverted shape."""
    closes = [start + i * trend_step for i in range(n_trend)]
    rows = []
    for i, c in enumerate(closes):
        o = c - trend_step * 0.3 if trend_step != 0 else c
        rows.append({
            "open": o,
            "high": max(o, c) + abs(trend_step) * 0.1,
            "low": min(o, c) - abs(trend_step) * 0.1,
            "close": c,
            "volume": 100.0,
        })

    last = closes[-1]
    if shape == "hammer":
        # Small body near high, long lower wick (~3x body), tiny upper wick.
        body = 40.0
        open_ = last
        close = last + body
        high = close + 5.0
        low = open_ - 3.0 * body
    elif shape == "inverted":
        body = 40.0
        open_ = last
        close = last + body
        low = open_ - 5.0
        high = close + 3.0 * body
    else:
        raise ValueError(f"Unknown shape: {shape}")

    rows.append({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100.0,
    })
    return pd.DataFrame(rows)


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


def test_hammer_after_downtrend_not_hanging_man():
    """Hammer shape after a downtrend is bullish hammer only."""
    df = _trend_then_shape(n_trend=20, trend_step=-80.0, shape="hammer")
    out = CandlestickPatternEngine().compute_all(df)
    assert int(out["cdl_hammer"].iloc[-1]) == 1
    assert int(out["cdl_hanging_man"].iloc[-1]) == 0


def test_hanging_man_after_uptrend_not_hammer():
    """Same hammer shape after an uptrend is hanging man only."""
    df = _trend_then_shape(n_trend=20, trend_step=80.0, shape="hammer")
    out = CandlestickPatternEngine().compute_all(df)
    assert int(out["cdl_hanging_man"].iloc[-1]) == 1
    assert int(out["cdl_hammer"].iloc[-1]) == 0


def test_inverted_hammer_after_downtrend_not_shooting_star():
    """Inverted shape after a downtrend is inverted hammer only."""
    df = _trend_then_shape(n_trend=20, trend_step=-80.0, shape="inverted")
    out = CandlestickPatternEngine().compute_all(df)
    assert int(out["cdl_inv_hammer"].iloc[-1]) == 1
    assert int(out["cdl_shooting_star"].iloc[-1]) == 0


def test_shooting_star_after_uptrend_not_inverted_hammer():
    """Inverted shape after an uptrend is shooting star only."""
    df = _trend_then_shape(n_trend=20, trend_step=80.0, shape="inverted")
    out = CandlestickPatternEngine().compute_all(df)
    assert int(out["cdl_shooting_star"].iloc[-1]) == 1
    assert int(out["cdl_inv_hammer"].iloc[-1]) == 0


def test_hammer_hanging_man_mutually_exclusive():
    """No bar may fire both hammer and hanging man."""
    df = _make_ohlcv(200)
    out = CandlestickPatternEngine().compute_all(df)
    both = (out["cdl_hammer"] == 1) & (out["cdl_hanging_man"] == 1)
    assert not both.any()


def test_inv_hammer_shooting_star_mutually_exclusive():
    """No bar may fire both inverted hammer and shooting star."""
    df = _make_ohlcv(200)
    out = CandlestickPatternEngine().compute_all(df)
    both = (out["cdl_inv_hammer"] == 1) & (out["cdl_shooting_star"] == 1)
    assert not both.any()


def test_flat_prior_trend_fires_neither_hammer_pair():
    """Hammer shape with flat prior trend is neither hammer nor hanging man."""
    n = 20
    close = np.full(n, 50000.0)
    df = pd.DataFrame({
        "open": close.copy(),
        "high": close + 10.0,
        "low": close - 10.0,
        "close": close,
        "volume": np.full(n, 100.0),
    })
    # Append classic hammer geometry on a flat tape.
    body = 40.0
    open_ = 50000.0
    close_px = open_ + body
    df = pd.concat([
        df,
        pd.DataFrame([{
            "open": open_,
            "high": close_px + 5.0,
            "low": open_ - 3.0 * body,
            "close": close_px,
            "volume": 100.0,
        }]),
    ], ignore_index=True)
    out = CandlestickPatternEngine().compute_all(df)
    assert int(out["cdl_hammer"].iloc[-1]) == 0
    assert int(out["cdl_hanging_man"].iloc[-1]) == 0
