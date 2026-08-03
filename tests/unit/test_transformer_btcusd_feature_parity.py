"""Train/serve parity tests for per-TF BTCUSD transformer features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    FEATURE_COLS,
    RESOLUTION_MINUTES,
    SUPPORTED_RESOLUTIONS,
    default_training_config,
)
from feature_store.transformer_btcusd.features import (
    assemble_raw_frame,
    build_feature_matrix,
    latest_closed_feature_row,
    prepare_raw_frame,
    validate_feature_columns,
)
from feature_store.transformer_btcusd.inference import build_inference_window, zscore_window


def _synthetic_ohlcv(n: int = 300, *, freq: str = "15min") -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = 50000 + np.cumsum(np.random.default_rng(42).normal(0, 20, n))
    return pd.DataFrame(
        {
            "time": ts,
            "open": close - 5,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )


def _misaligned_derivatives(ohlcv: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Funding/OI timestamps offset from OHLCV (exercises merge_asof path)."""
    fund_times = ohlcv["time"].iloc[::2].reset_index(drop=True)
    oi_times = ohlcv["time"].iloc[1::2].reset_index(drop=True)
    funding_df = pd.DataFrame(
        {
            "time": fund_times,
            "funding_rate": np.linspace(0.0001, 0.0002, len(fund_times)),
        }
    )
    oi_df = pd.DataFrame(
        {
            "time": oi_times,
            "open_interest": np.linspace(1e6, 1.1e6, len(oi_times)),
        }
    )
    return funding_df, oi_df


def test_default_training_config_early_stopping_enabled() -> None:
    cfg = default_training_config("15m")
    assert cfg["early_stopping_enabled"] is True
    assert cfg["epochs"] == 120
    assert cfg["early_stop_patience"] == 12


def test_assemble_raw_frame_matches_prepare_raw_frame() -> None:
    ohlcv = _synthetic_ohlcv(50)
    funding_df, oi_df = _misaligned_derivatives(ohlcv)
    assembled = assemble_raw_frame(ohlcv, funding_df=funding_df, oi_df=oi_df)
    prepared = prepare_raw_frame(ohlcv, funding_df=funding_df, oi_df=oi_df)
    for col in ("funding_rate", "open_interest"):
        assert assembled[col].equals(prepared[col])


def test_assemble_raw_frame_ffills_misaligned_derivatives() -> None:
    ohlcv = _synthetic_ohlcv(40, freq="15min")
    funding_df, oi_df = _misaligned_derivatives(ohlcv)
    assembled = assemble_raw_frame(ohlcv, funding_df=funding_df, oi_df=oi_df)
    exact = ohlcv.merge(funding_df, on="time", how="left")
    assert exact["funding_rate"].isna().sum() > 0
    assert assembled["funding_rate"].isna().sum() == 0
    assert assembled["open_interest"].isna().sum() == 0


@pytest.mark.parametrize("resolution", SUPPORTED_RESOLUTIONS)
def test_inference_window_matches_window_dataset_zscore(resolution: str) -> None:
    minutes = RESOLUTION_MINUTES[resolution]
    freq = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h"}[resolution]
    n = max(400, int(round(96 * minutes / 5)) + 200)
    ohlcv = _synthetic_ohlcv(n, freq=freq)
    funding_df, oi_df = _misaligned_derivatives(ohlcv)
    raw = assemble_raw_frame(ohlcv, funding_df=funding_df, oi_df=oi_df)
    feat_df = build_feature_matrix(raw, resolution_minutes=minutes, dropna=True)
    window_len = 128
    values = feat_df[list(FEATURE_COLS)].values.astype(np.float32)
    inference_window = build_inference_window(values, window_len=window_len)

    tail = values[-window_len:]
    dataset_window = zscore_window(tail)
    np.testing.assert_allclose(inference_window[0], dataset_window, rtol=1e-5, atol=1e-5)


def test_closed_bar_row_is_second_to_last_after_dropna() -> None:
    raw = _synthetic_ohlcv(400, freq="15min")
    funding_df, oi_df = _misaligned_derivatives(raw)
    feat_df = build_feature_matrix(
        assemble_raw_frame(raw, funding_df=funding_df, oi_df=oi_df),
        resolution_minutes=15,
        dropna=True,
    )
    closed = latest_closed_feature_row(feat_df)
    assert closed.name == len(feat_df) - 2


def test_validate_feature_columns_finite_closed_bar() -> None:
    raw = _synthetic_ohlcv(400, freq="15min")
    funding_df, oi_df = _misaligned_derivatives(raw)
    feat_df = build_feature_matrix(
        assemble_raw_frame(raw, funding_df=funding_df, oi_df=oi_df),
        resolution_minutes=15,
        dropna=True,
    )
    validate_feature_columns(feat_df, require_finite_closed_bar=True)


def test_train_runner_feature_path_matches_node_pipeline() -> None:
    """Mirror TransformerModelNode feature assembly on shared synthetic data."""
    raw = _synthetic_ohlcv(400, freq="15min")
    funding_df, oi_df = _misaligned_derivatives(raw)
    node_raw = prepare_raw_frame(raw, funding_df=funding_df, oi_df=oi_df)
    train_raw = assemble_raw_frame(raw, funding_df=funding_df, oi_df=oi_df)
    node_feat = build_feature_matrix(node_raw, resolution_minutes=15, dropna=True)
    train_feat = build_feature_matrix(train_raw, resolution_minutes=15, dropna=True)
    assert len(node_feat) == len(train_feat)
    for col in FEATURE_COLS:
        np.testing.assert_allclose(
            node_feat[col].values,
            train_feat[col].values,
            rtol=1e-5,
            atol=1e-5,
            err_msg=f"parity failure for {col}",
        )
