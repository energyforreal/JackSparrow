"""Unit tests for vectorized L1 candle class ids."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import CANDLE_CLASS_CARDINALITY, CANDLE_CLASS_COL
from feature_store.transformer_btcusd.features import add_features, classify_candle_shape


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


def _set_last_bar(
    df: pd.DataFrame,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> pd.DataFrame:
    out = df.copy()
    i = out.index[-1]
    out.loc[i, ["open", "high", "low", "close"]] = [open_, high, low, close]
    return out


def _last_class(df: pd.DataFrame) -> int:
    feat = add_features(df, resolution_minutes=5)
    return int(feat[CANDLE_CLASS_COL].iloc[-1])


def test_flat_zero_range_is_class_zero() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    labeled = _set_last_bar(df, open_=px, high=px, low=px, close=px)
    assert _last_class(labeled) == 0


def test_dragonfly_doji_class() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    labeled = _set_last_bar(df, open_=px, high=px, low=px - 80.0, close=px)
    assert _last_class(labeled) == 1


def test_gravestone_doji_class() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    labeled = _set_last_bar(df, open_=px, high=px + 80.0, low=px, close=px)
    assert _last_class(labeled) == 2


def test_marubozu_bull_class() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    labeled = _set_last_bar(df, open_=px, high=px + 50.0, low=px, close=px + 50.0)
    assert _last_class(labeled) == 4


def test_marubozu_bear_class() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    labeled = _set_last_bar(df, open_=px, high=px, low=px - 50.0, close=px - 50.0)
    assert _last_class(labeled) == 5


def test_hammer_shape_class() -> None:
    df = _base_ohlcv()
    px = float(df["close"].iloc[-2])
    labeled = _set_last_bar(
        df,
        open_=px + 7.5,
        high=px + 10.0,
        low=px,
        close=px + 10.0,
    )
    assert _last_class(labeled) == 6


def test_every_row_in_valid_range() -> None:
    feat = add_features(_base_ohlcv(300), resolution_minutes=5)
    ids = feat[CANDLE_CLASS_COL]
    assert ids.dtype == np.int64 or str(ids.dtype).startswith("int")
    assert ((ids >= 0) & (ids <= CANDLE_CLASS_CARDINALITY - 1)).all()
    assert not ids.isna().any()


def test_classify_is_causal_prefix_match() -> None:
    df = _base_ohlcv(120)
    full = add_features(df, resolution_minutes=5)
    for i in (40, 80, 119):
        prefix = add_features(df.iloc[: i + 1].copy(), resolution_minutes=5)
        assert int(prefix[CANDLE_CLASS_COL].iloc[-1]) == int(full[CANDLE_CLASS_COL].iloc[i])


def test_classify_candle_shape_requires_ratio_columns() -> None:
    df = _base_ohlcv(40)
    feat = add_features(df, resolution_minutes=5)
    ids = classify_candle_shape(feat, sr_window=96)
    assert len(ids) == len(feat)
    assert ((ids >= 0) & (ids <= 12)).all()
