"""Tests for 3-class fusion horizon labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    FUSION_DIR_COLS,
    HORIZON_DIR_ATR_WEAK,
    MAX_FUSION_HORIZON_BARS,
)
from feature_store.transformer_btcusd.mtf_labels import (
    compute_fusion_horizon_labels,
    fusion_future_leak_cols,
    three_class_direction,
    trim_fusion_label_tail,
)


def test_three_class_dead_zone() -> None:
    atr = 10.0
    assert three_class_direction(4.0, atr) == 1  # 0.4 ATR → NEUTRAL
    assert three_class_direction(5.0, atr) == 2  # 0.5 ATR → BULL
    assert three_class_direction(-5.0, atr) == 0
    assert abs(HORIZON_DIR_ATR_WEAK - 0.5) < 1e-9


def test_horizon_labels_use_future_close_only() -> None:
    n = 80
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 100.0)
    close[40:] = 120.0
    df = pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
            "atr": 1.0,
        }
    )
    labeled = compute_fusion_horizon_labels(df)
    # At t=38, +10m is t=40 where close jumped → BULL
    assert int(labeled.loc[38, "h10m_dir"]) == 2
    # Last 24 rows cannot form +2h labels
    assert pd.isna(labeled.iloc[-1]["h2h_dir"])
    trimmed = trim_fusion_label_tail(labeled)
    assert len(trimmed) == n - MAX_FUSION_HORIZON_BARS
    assert trimmed["h2h_dir"].notna().all()


def test_label_cols_are_leakage() -> None:
    leaked = fusion_future_leak_cols()
    for col in FUSION_DIR_COLS:
        assert col in leaked
    assert "ret_1" not in leaked
