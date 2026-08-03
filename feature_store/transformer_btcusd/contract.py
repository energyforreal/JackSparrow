"""Constants shared between per-TF Colab training and agent inference."""

from __future__ import annotations

from typing import Any, Dict, Tuple

# Bump when FEATURE_COLS or semantics change (requires retrain + re-export).
FEATURE_CONTRACT_VERSION = "transformer_btcusd_per_tf_features_v1"

SUPPORTED_RESOLUTIONS: Tuple[str, ...] = ("5m", "15m", "30m", "1h", "2h")

RESOLUTION_MINUTES: Dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
}

TF_KEYS: Tuple[str, ...] = tuple(f"tf_{r}" for r in SUPPORTED_RESOLUTIONS)

FEATURE_COLS: Tuple[str, ...] = (
    "ret_1",
    "rv_16",
    "rv_96",
    "ema50_dist_pct",
    "macd_hist",
    "rsi_14",
    "adx_14",
    "obv_z",
    "vol_z",
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "dist_to_resistance_pct",
    "dist_to_support_pct",
    "funding_rate",
    "oi_z",
    "funding_zscore",
    "funding_mom",
    "funding_rate_roc",
    "oi_change_2",
    "oi_delta_z",
    "oi_price_divergence",
    "oi_acceleration",
    "funding_x_oi",
)

RETURN_COL = "future_return"

PATH_LABEL_COLS: Tuple[str, ...] = (
    "mfe",
    "mae",
    "future_volatility",
    "trend_strength",
    "drawdown_before_mfe",
    "future_oi_change_pct",
    "future_volume_change_pct",
)

CONTINUOUS_LABEL_COLS: Tuple[str, ...] = (RETURN_COL,) + PATH_LABEL_COLS

PATH_LABEL_HORIZON_BARS: int = 8

# Reference Colab notebook (btcusd_15m_transformer) uses 32 bars on 15m (~8h wall-clock).
REFERENCE_LABEL_HORIZON_MINUTES: int = 480

REGIME_NAMES: Dict[int, str] = {
    0: "LOW",
    1: "NORMAL",
    2: "HIGH",
    3: "EXTREME",
}

# Minimum test-set correlation for future_return before ONNX export.
MIN_EXPORT_RETURN_CORR: Dict[str, float] = {
    "5m": 0.03,
    "15m": 0.04,
    "30m": 0.03,
    "1h": 0.02,
    "2h": 0.02,
}

TRANSFORMER_METADATA_FILENAME = "metadata_transformer.json"
TRANSFORMER_FEATURE_CONFIG_FILENAME = "feature_config.json"


def model_family_for_resolution(resolution: str) -> str:
    """Canonical model_family string for a TF bundle."""
    res = resolution.strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    return f"jacksparrow_transformer_btcusd_{res}"


def onnx_filename_for_resolution(resolution: str) -> str:
    res = resolution.strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    return f"btcusd_{res}_transformer.onnx"


def bundle_dir_name(resolution: str) -> str:
    res = resolution.strip().lower()
    return f"JackSparrow_Transformer_BTCUSD_{res}"


def label_horizon_bars_for_resolution(resolution_minutes: int) -> int:
    """Forward label window in bars (~8h wall-clock; 32 bars on 15m per reference notebook)."""
    return max(1, int(round(REFERENCE_LABEL_HORIZON_MINUTES / resolution_minutes)))


def default_training_config(resolution: str) -> Dict[str, Any]:
    """Default Colab training config for a single TF model."""
    res = resolution.strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    minutes = RESOLUTION_MINUTES[res]
    label_horizon = label_horizon_bars_for_resolution(minutes)
    return {
        "symbol": "BTCUSD",
        "resolution": res,
        "resolution_minutes": minutes,
        "history_days": 900,
        "base_url": "https://api.india.delta.exchange",
        "atr_period": 14,
        "return_horizon_bars": label_horizon,
        "path_label_horizon_bars": label_horizon,
        "mae_floor_atr_mult": 0.25,
        "vol_regime_quantiles": [0.25, 0.5, 0.75],
        "window_len": 128,
        "stride": 8,
        "train_frac": 0.65,
        "val_frac": 0.15,
        "embargo_bars": label_horizon,
        "batch_size": 128,
        "epochs": 200,
        "lr": 1e-4,
        "d_model": 64,
        "nhead": 4,
        "num_layers": 2,
        "dropout": 0.25,
        "weight_decay": 1e-2,
        "early_stop_patience": 10,
        "early_stopping_enabled": False,
        "min_derivatives_coverage": 0.5,
        "derivatives_coverage_warn": 0.9,
        "min_export_return_corr": MIN_EXPORT_RETURN_CORR.get(res, 0.02),
        "default_threshold": 0.005,
        "seed": 42,
    }


def max_label_horizon_bars(
    return_horizon_bars: int = 1,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
) -> int:
    """Maximum forward bars across all training labels."""
    return max(int(return_horizon_bars), int(path_label_horizon_bars))


def scale_period(period: int, resolution_minutes: int, *, base_minutes: int = 5) -> int:
    """Scale indicator lookback to preserve wall-clock semantics across TFs."""
    return max(1, int(round(period * resolution_minutes / base_minutes)))
