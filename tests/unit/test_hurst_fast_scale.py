"""Lock the known scale behavior of Hurst estimators (legacy vs v2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_mcp_row import _hurst_fast, _hurst_variance_ratio_v2


def _rw_close(n: int = 500, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    log_ret = rng.normal(0.0, 0.01, size=n)
    return pd.Series(100.0 * np.exp(np.cumsum(log_ret)))


def test_hurst_fast_random_walk_maps_near_zero_not_half() -> None:
    """Classic Hurst RW≈0.5; legacy estimator maps iid returns ≈0 (then clips).

    H = 0.5 + 0.5 * log(Var(mean_4) / Var(1)) / log(4)
    For iid returns Var(mean_4)/Var(1) ≈ 1/4 → H ≈ 0.
    """
    h = _hurst_fast(_rw_close(), window=60).dropna()
    assert len(h) > 100
    assert float(h.median()) < 0.15
    assert float((h <= 0.05).mean()) > 0.5


def test_hurst_v2_random_walk_maps_near_half() -> None:
    """Corrected variance-ratio uses sum aggregation → RW ≈ 0.5."""
    h = _hurst_variance_ratio_v2(_rw_close(), window=60).dropna()
    assert len(h) > 100
    med = float(h.median())
    assert 0.35 <= med <= 0.65


def test_hurst_fast_fillna_missing_is_half_not_zero() -> None:
    close = pd.Series([100.0, 100.1, 99.9])  # far below min_periods for window=60
    h = _hurst_fast(close, window=60)
    # Warmup NaNs become 0.5 — distinct from clip floor 0.0
    assert float(h.iloc[-1]) == 0.5


def test_hurst_v2_fillna_missing_is_half() -> None:
    close = pd.Series([100.0, 100.1, 99.9])
    h = _hurst_variance_ratio_v2(close, window=60)
    assert float(h.iloc[-1]) == 0.5
