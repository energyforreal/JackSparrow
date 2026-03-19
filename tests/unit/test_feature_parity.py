"""
Feature parity tests: verify batch and single compute produce identical values.

Ensures train-serve parity for UnifiedFeatureEngine.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from feature_store.unified_feature_engine import UnifiedFeatureEngine
from feature_store.feature_registry import FEATURE_LIST, CANDLESTICK_FEATURES


def _make_test_df(n: int = 150) -> pd.DataFrame:
    """Create synthetic OHLCV DataFrame."""
    np.random.seed(42)
    base = 50000
    returns = np.random.randn(n).cumsum() * 0.002
    close = base * (1 + returns)
    high = close * (1 + np.abs(np.random.randn(n) * 0.005))
    low = close * (1 - np.abs(np.random.randn(n) * 0.005))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(100, 1000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume
    })


@pytest.mark.parametrize("feature_name", FEATURE_LIST[:10])  # Test subset for speed
def test_canonical_feature_parity(feature_name: str):
    """Batch last-row value matches compute_single for canonical features."""
    df = _make_test_df(100)
    candles = df.to_dict("records")

    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(df, fill_invalid=True)
    single_val = engine.compute_single(feature_name, candles, resolution_minutes=15)

    batch_val = float(batch[feature_name].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5, (
        f"Parity failure for {feature_name}: batch={batch_val:.8f}, single={single_val:.8f}"
    )


def test_candlestick_feature_parity():
    """Batch last-row matches compute_single for candlestick features."""
    df = _make_test_df(150)
    candles = df.to_dict("records")

    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(df, fill_invalid=True, include_pattern_features=True)
    single_val = engine.compute_single("cdl_doji", candles)

    batch_val = float(batch["cdl_doji"].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5


def test_full_canonical_parity():
    """All 50 canonical features have parity."""
    df = _make_test_df(100)
    candles = df.to_dict("records")
    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(df, fill_invalid=True)

    for name in FEATURE_LIST:
        single_val = engine.compute_single(name, candles)
        batch_val = float(batch[name].iloc[-1])
        assert abs(batch_val - single_val) < 1e-5, f"Parity failure: {name}"
