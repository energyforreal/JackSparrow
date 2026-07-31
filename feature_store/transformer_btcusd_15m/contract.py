"""Constants shared between Colab training and agent inference."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Bump when FEATURE_COLS or semantics change (requires retrain + re-export).
FEATURE_CONTRACT_VERSION = "transformer_btcusd_15m_features_v2"

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
    "h1_trend",
    "h1_rsi_14",
    "h1_adx",
    "h1_vol_regime",
    "funding_zscore",
    "funding_mom",
    "funding_rate_roc",
    "oi_change_2",
    "oi_delta_z",
    "oi_price_divergence",
    "oi_acceleration",
    "funding_x_oi",
)

HORIZON_RETURN_COLS: Tuple[str, ...] = (
    "future_return_scalp_10m",
    "future_return_intraday_30m",
    "future_return_trend_1h",
    "future_return_swing_2h",
)

PATH_LABEL_COLS: Tuple[str, ...] = (
    "mfe",
    "mae",
    "future_volatility",
    "trend_strength",
    "drawdown_before_mfe",
    "future_oi_change_pct",
    "future_volume_change_pct",
)

CONTINUOUS_LABEL_COLS: Tuple[str, ...] = HORIZON_RETURN_COLS + PATH_LABEL_COLS

# v43 horizon key -> forward bars on 15m grid.
RETURN_HORIZON_BARS: Dict[str, int] = {
    "scalp_10m": 1,
    "intraday_30m": 2,
    "trend_1h": 4,
    "swing_2h": 8,
}

HORIZON_KEY_TO_RETURN_COL: Dict[str, str] = {
    "scalp_10m": "future_return_scalp_10m",
    "intraday_30m": "future_return_intraday_30m",
    "trend_1h": "future_return_trend_1h",
    "swing_2h": "future_return_swing_2h",
}

PATH_LABEL_HORIZON_BARS: int = 8

# Legacy single-return column (transformer_v1 bundles).
LEGACY_RETURN_COL = "future_return"

REGIME_NAMES: Dict[int, str] = {
    0: "LOW",
    1: "NORMAL",
    2: "HIGH",
    3: "EXTREME",
}

DEFAULT_TRAINING_CONFIG: Dict[str, Any] = {
    "symbol": "BTCUSD",
    "resolution": "15m",
    "history_days": 900,
    "base_url": "https://api.india.delta.exchange",
    "atr_period": 14,
    "return_horizon_bars": dict(RETURN_HORIZON_BARS),
    "path_label_horizon_bars": PATH_LABEL_HORIZON_BARS,
    "mae_floor_atr_mult": 0.25,
    "vol_regime_quantiles": [0.25, 0.5, 0.75],
    "window_len": 128,
    "stride": 8,
    "train_frac": 0.65,
    "val_frac": 0.15,
    "embargo_bars": PATH_LABEL_HORIZON_BARS,
    "batch_size": 128,
    "epochs": 200,
    "lr": 1e-4,
    "d_model": 64,
    "nhead": 4,
    "num_layers": 2,
    "dropout": 0.25,
    "weight_decay": 1e-2,
    "early_stop_patience": 10,
    "early_stopping_enabled": True,
    "min_derivatives_coverage": 0.5,
    "derivatives_coverage_warn": 0.9,
    "seed": 42,
}

TRANSFORMER_MODEL_FAMILY = "jacksparrow_transformer_btcusd_15m"
TRANSFORMER_METADATA_FILENAME = "metadata_transformer.json"
TRANSFORMER_ONNX_FILENAME = "btcusd_15m_transformer.onnx"
TRANSFORMER_FEATURE_CONFIG_FILENAME = "feature_config.json"


def max_label_horizon_bars(
    return_horizon_bars: Dict[str, int] | None = None,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
) -> int:
    """Maximum forward bars across all training labels."""
    horizons = return_horizon_bars or RETURN_HORIZON_BARS
    return max(max(horizons.values()), int(path_label_horizon_bars))
