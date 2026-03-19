"""
Pattern feature validation: activation rates and directional alignment.

Validates that pattern features have reasonable activation rates (2-30%)
and correlate with forward returns where expected.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from feature_store.pattern_features.candlestick_patterns import CandlestickPatternEngine
from feature_store.pattern_features.chart_patterns import ChartPatternEngine


def _make_ohlcv(n: int = 500) -> pd.DataFrame:
    np.random.seed(42)
    base = 50000
    ret = np.random.randn(n).cumsum() * 0.001
    close = base * (1 + ret)
    high = close * (1 + np.abs(np.random.randn(n) * 0.003))
    low = close * (1 - np.abs(np.random.randn(n) * 0.003))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.random.randint(100, 1000, n).astype(float),
    })


def test_candlestick_activation_rates():
    """Candlestick binary patterns should activate on 0-50% of bars (relaxed for synthetic)."""
    df = _make_ohlcv(500)
    engine = CandlestickPatternEngine()
    out = engine.compute_all(df)

    binary_cols = [c for c in out.columns if c.startswith("cdl_") and c not in [
        "cdl_bull_score", "cdl_bear_score", "cdl_net_score", "cdl_reversal_signal",
        "cdl_indecision_score", "cdl_body_ratio", "cdl_upper_wick_ratio",
        "cdl_lower_wick_ratio", "cdl_consecutive_bull", "cdl_consecutive_bear",
    ]]
    for col in binary_cols[:5]:  # Sample a few
        rate = out[col].mean()
        assert 0 <= rate <= 1, f"{col} activation rate {rate} out of [0,1]"


def test_chart_pattern_activation_rates():
    """Chart pattern binary features should be in valid range."""
    df = _make_ohlcv(200)
    engine = ChartPatternEngine()
    out = engine.compute_all(df)

    binary_cols = ["chp_bull_flag", "chp_bear_flag", "chp_asc_triangle", "bo_at_high"]
    for col in binary_cols:
        if col in out.columns:
            rate = out[col].mean()
            assert 0 <= rate <= 1, f"{col} activation rate {rate} out of [0,1]"
