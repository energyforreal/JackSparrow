"""Tests for v43 MCP feature row (JackSparrow metadata_v43.json names)."""

import numpy as np

from feature_store.jacksparrow_v43_mcp_row import (
    V43_MCP_FEATURE_NAMES,
    build_v43_last_row,
)


def _synthetic_candles(n: int = 320, seed: int = 42):
    rng = np.random.default_rng(seed)
    base_ts = 1700000000
    step = 300  # 5m
    price = 50000 + np.cumsum(rng.normal(0, 50, size=n))
    candles = []
    for i in range(n):
        c = float(max(price[i], 1000))
        noise = rng.uniform(10, 80)
        o = c - rng.uniform(-20, 20)
        h = max(o, c) + noise
        l = min(o, c) - noise * 0.8
        v = float(rng.uniform(50, 500))
        candles.append(
            {
                "timestamp": base_ts + i * step,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": v,
            }
        )
    return candles


def test_v43_row_has_all_metadata_features():
    row = build_v43_last_row(_synthetic_candles(), primary_interval="5m")
    for name in V43_MCP_FEATURE_NAMES:
        assert name in row
        assert isinstance(row[name], float)
        assert np.isfinite(row[name])


def test_v43_row_empty_returns_zeros():
    row = build_v43_last_row([])
    assert row == {n: 0.0 for n in V43_MCP_FEATURE_NAMES}
