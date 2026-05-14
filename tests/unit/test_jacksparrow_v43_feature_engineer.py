"""JackSparrowV43FeatureEngineer wraps build_v43_feature_matrix + training target."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES, V43_FORWARD_TARGET_BARS
from feature_store.jacksparrow_v43_feature_engineer import JackSparrowV43FeatureEngineer


def _synth_5m(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    close = 40000 + np.cumsum(rng.normal(0, 20, size=n))
    noise = rng.uniform(5, 40, size=n)
    o = close - rng.normal(0, 10, size=n)
    h = np.maximum(o, close) + noise
    l = np.minimum(o, close) - noise * 0.9
    v = rng.uniform(10, 1000, size=n)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": o,
            "high": h,
            "low": l,
            "close": close,
            "volume": v,
        }
    )


def test_transform_inference_columns():
    fe = JackSparrowV43FeatureEngineer()
    df5 = _synth_5m(500)
    dfz = pd.DataFrame()
    out = fe.transform(df5, df5, df5, dfz, include_target=False)
    assert not out.empty
    for c in V43_CANONICAL_FEATURES:
        assert c in out.columns


def test_transform_with_target_horizon():
    fe = JackSparrowV43FeatureEngineer()
    df5 = _synth_5m(500)
    out = fe.transform(df5, df5, df5, pd.DataFrame(), include_target=True)
    assert "target" in out.columns
    h = int(V43_FORWARD_TARGET_BARS)
    assert pd.isna(out["target"].iloc[-1])
    # Last index with a full h-bar future: n - 1 - h
    last_valid = len(out) - 1 - h
    assert last_valid >= 0
    assert np.isfinite(float(out["target"].iloc[last_valid]))
    assert pd.isna(out["target"].iloc[last_valid + 1])
    assert np.isfinite(float(out["target"].iloc[100]))
