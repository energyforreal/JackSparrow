"""Unit tests for v43 basis features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_basis_features import _basis_features_on_primary


def _primary(n: int = 60) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 100.0 + np.arange(n) * 0.1
    return pd.DataFrame({"timestamp": ts, "close": close})


def test_basis_features_from_mark_and_spot() -> None:
    prim = _primary(60)
    ts = prim["timestamp"]
    mark = pd.DataFrame({"timestamp": ts, "close": prim["close"] + 2.0})
    ticker = pd.DataFrame({"timestamp": ts, "spot_price": prim["close"]})
    out = _basis_features_on_primary(prim, mark, ticker)
    assert "basis" in out.columns
    assert out["basis"].iloc[-1] > 0
    assert abs(out["basis_zscore"].iloc[-1]) <= 4.0


def test_basis_features_zero_when_missing() -> None:
    prim = _primary(20)
    out = _basis_features_on_primary(prim, None, None)
    assert out["basis"].sum() == 0.0
