"""Tests for per-TF path label horizons and training config defaults."""

from __future__ import annotations

import pytest

from feature_store.transformer_btcusd.contract import (
    CONTINUOUS_LABEL_COLS,
    default_training_config,
    path_label_horizon_bars_for_resolution,
    SUPPORTED_RESOLUTIONS,
)


@pytest.mark.parametrize("resolution", SUPPORTED_RESOLUTIONS)
def test_path_horizon_positive(resolution: str) -> None:
    assert path_label_horizon_bars_for_resolution(resolution) >= 1


def test_5m_path_horizon() -> None:
    assert path_label_horizon_bars_for_resolution("5m") == 48


def test_15m_path_horizon() -> None:
    assert path_label_horizon_bars_for_resolution("15m") == 16


def test_2h_path_horizon_eight_hours() -> None:
    assert path_label_horizon_bars_for_resolution("2h") == 4


def test_default_training_config_path_only() -> None:
    cfg = default_training_config("15m")
    assert "return_horizon_bars" not in cfg
    assert cfg["path_label_horizon_bars"] == 16
    assert cfg["embargo_bars"] == 16
    assert cfg["min_export_vol_corr"] == 0.10
    weights = cfg["continuous_loss_weights"]
    assert len(weights) == len(CONTINUOUS_LABEL_COLS)
    vol_idx = CONTINUOUS_LABEL_COLS.index("future_volume_change_pct")
    assert weights[vol_idx] == 0.0
    follow_idx = CONTINUOUS_LABEL_COLS.index("candle_follow_through_atr")
    delta_idx = CONTINUOUS_LABEL_COLS.index("structure_delta")
    assert weights[follow_idx] == 0.5
    assert weights[delta_idx] == 0.5
