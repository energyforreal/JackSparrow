"""Tests for 2-class fusion horizon labels (NEUTRAL ignored in training)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    FUSION_DIR_COLS,
    FUSION_IGNORE_INDEX,
    HORIZON_DIR_ATR_WEAK,
    MAX_FUSION_HORIZON_BARS,
    N_FUSION_HORIZONS,
)
from feature_store.transformer_btcusd.mtf_labels import (
    compute_fusion_horizon_labels,
    fusion_future_leak_cols,
    fusion_label_matrix,
    horizon_atr_weak,
    label_class_mix,
    three_class_direction,
    three_class_to_train_label,
    trim_fusion_label_tail,
    valid_label_mask,
)


def test_three_class_dead_zone() -> None:
    atr = 10.0
    assert three_class_direction(4.0, atr) == 1  # 0.4 ATR → NEUTRAL
    assert three_class_direction(5.0, atr) == 2  # 0.5 ATR → BULL
    assert three_class_direction(-5.0, atr) == 0
    assert abs(HORIZON_DIR_ATR_WEAK - 0.5) < 1e-9


def test_neutral_maps_to_ignore_index() -> None:
    assert three_class_to_train_label(0) == 0
    assert three_class_to_train_label(2) == 1
    assert three_class_to_train_label(1) == FUSION_IGNORE_INDEX
    assert three_class_to_train_label(float("nan")) == FUSION_IGNORE_INDEX


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
    # At t=38, +30m is t=44 where close has already jumped → internal BULL (2)
    assert "h10m_dir" not in labeled.columns
    assert int(labeled.loc[38, "h30m_dir"]) == 2
    assert pd.isna(labeled.iloc[-1]["h2h_dir"])
    trimmed = trim_fusion_label_tail(labeled)
    assert len(trimmed) == n - MAX_FUSION_HORIZON_BARS
    assert trimmed["h2h_dir"].notna().all()
    y = fusion_label_matrix(trimmed)
    assert y.shape[1] == N_FUSION_HORIZONS
    assert y.shape[1] == 3
    assert int(y[38, 0]) == 1  # BULL train id


def test_fusion_label_matrix_ignores_neutral() -> None:
    n = 40
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 100.0)
    df = pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1.0,
            "atr": 10.0,
        }
    )
    labeled = compute_fusion_horizon_labels(df)
    y = fusion_label_matrix(trim_fusion_label_tail(labeled))
    mix = label_class_mix(y)
    for key, row in mix.items():
        assert row["IGNORED"] > 0
        assert row["ignore_rate"] > 0.5
        assert row["BEAR"] + row["BULL"] + row["IGNORED"] == y.shape[0]
    assert valid_label_mask(y).sum() == 0


def test_h2h_dead_zone_wider_than_h30m() -> None:
    n = 80
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 100.0)
    close[6:] = 106.0
    df = pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
            "atr": 10.0,
        }
    )
    labeled = compute_fusion_horizon_labels(df)
    assert horizon_atr_weak("h30m") == 0.5
    assert horizon_atr_weak("h2h") == 0.75
    assert int(labeled.loc[0, "h30m_dir"]) == 2
    assert int(labeled.loc[0, "h2h_dir"]) == 1


def test_label_cols_are_leakage() -> None:
    leaked = fusion_future_leak_cols()
    for col in FUSION_DIR_COLS:
        assert col in leaked
    assert "h10m_dir" in leaked
    assert "ret_1" not in leaked
