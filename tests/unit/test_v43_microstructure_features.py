"""Unit tests for v43 microstructure features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_microstructure_features import (
    _microstructure_features_on_primary,
)


def _primary(n: int = 40) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "close": np.linspace(100, 101, n)})


def test_microstructure_imbalance_and_spread() -> None:
    prim = _primary(40)
    ts = prim["timestamp"]
    ticker = pd.DataFrame(
        {
            "timestamp": ts,
            "bid_size": 120.0,
            "ask_size": 80.0,
            "best_bid": 99.5,
            "best_ask": 100.5,
            "mark_price": 100.0,
            "predicted_funding_rate": 0.0001,
        }
    )
    fz = pd.Series(0.5, index=range(len(prim)))
    oz = pd.Series(1.2, index=range(len(prim)))
    out = _microstructure_features_on_primary(prim, ticker, fz, oz)
    assert out["bid_ask_imbalance"].iloc[-1] > 0
    assert out["spread_bps"].iloc[-1] > 0
    assert out["funding_x_oi"].iloc[-1] > 0


def test_microstructure_zero_when_no_ticker() -> None:
    prim = _primary(20)
    fz = pd.Series(0.0, index=range(20))
    oz = pd.Series(0.0, index=range(20))
    out = _microstructure_features_on_primary(prim, None, fz, oz)
    assert out["bid_ask_imbalance"].sum() == 0.0
