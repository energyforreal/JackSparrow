"""Quick BTCUSD-like label balance check for MSO v50."""
from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_labels import (
    build_breakout_state_labels,
    build_compression_expansion_labels,
    build_liquidity_condition_labels,
    build_momentum_quality_labels,
    build_trend_regime_labels,
    build_vol_regime_labels,
)

n = 10000
rng = np.random.default_rng(99)
split = int(n * 0.8)
close = pd.Series(45000 + np.cumsum(rng.normal(0, 15, n)))
high = close + rng.uniform(20, 120, n)
low = close - rng.uniform(20, 120, n)
df = pd.DataFrame(
    {
        "high": high.values,
        "low": low.values,
        "rsi_14": rng.normal(50, 7, n).clip(25, 75),
        "rsi_mom": rng.normal(0, 0.35, n),
        "trend_mom": rng.normal(0, 0.00025, n),
        "oi_price_divergence": rng.normal(0, 0.004, n),
        "oi_zscore": rng.normal(0.3, 0.5, n),
        "funding_zscore": rng.normal(0.1, 0.4, n),
        "wick_asym": rng.normal(0, 0.2, n),
        "oi_acceleration": rng.normal(0, 0.0015, n),
        "bb_width": rng.uniform(0.005, 0.018, n),
        "adx_14": rng.uniform(8, 22, n),
        "hurst_60": rng.uniform(0.43, 0.57, n),
    }
)

cases = [
    ("trend", build_trend_regime_labels, dict(forward_bars=6, train_end_idx=split), False),
    ("vol", build_vol_regime_labels, dict(forward_bars=2, train_end_idx=split), True),
    ("breakout", build_breakout_state_labels, dict(forward_bars=2, train_end_idx=split), True),
    ("liquidity", build_liquidity_condition_labels, dict(forward_bars=6, train_end_idx=split), True),
    ("momentum", build_momentum_quality_labels, dict(forward_bars=6, train_end_idx=split), False),
    ("compression", build_compression_expansion_labels, dict(forward_bars=6), True),
]

for name, fn, kwargs, needs_close in cases:
    if needs_close:
        labels, stats = fn(df, close, **kwargs)
    else:
        labels, stats = fn(df, **kwargs)
    vc = labels.value_counts()
    total = labels.notna().sum()
    top_pct = 100 * vc.iloc[0] / total if total else 0
    n_classes = sum(1 for v in stats["class_counts"].values() if v >= 50)
    print(f"{name:12s} top={str(vc.index[0]):22s} {top_pct:4.0f}%  classes>=50: {n_classes}")
    print(f"             counts={stats['class_counts']}")
