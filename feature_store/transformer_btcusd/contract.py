"""Constants shared between per-TF Colab training and agent inference."""

from __future__ import annotations

from typing import Any, Dict, Tuple

# Bump when FEATURE_COLS or semantics change (requires retrain + re-export).
FEATURE_CONTRACT_VERSION = "transformer_btcusd_per_tf_features_v3"

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

PATH_LABEL_COLS: Tuple[str, ...] = (
    "mfe",
    "mae",
    "future_volatility",
    "trend_strength",
    "drawdown_before_mfe",
    "future_oi_change_pct",
    "future_volume_change_pct",
)

CONTINUOUS_LABEL_COLS: Tuple[str, ...] = PATH_LABEL_COLS

PATH_LABEL_HORIZON_BARS: int = 8

# Legacy 8h reference (btcusd_15m_transformer used 32 bars on 15m).
REFERENCE_LABEL_HORIZON_MINUTES: int = 480

DEFAULT_PATH_LABEL_HORIZON_MINUTES: Dict[str, int] = {
    "5m": 240,
    "15m": 240,
    "30m": 480,
    "1h": 480,
    "2h": 480,
}

# Volume change excluded from loss (dominates shared encoder).
DEFAULT_CONTINUOUS_LOSS_WEIGHTS: Dict[str, float] = {
    "mfe": 0.5,
    "mae": 0.5,
    "future_volatility": 1.0,
    "trend_strength": 0.5,
    "drawdown_before_mfe": 0.5,
    "future_oi_change_pct": 0.25,
    "future_volume_change_pct": 0.0,
}

REGIME_NAMES: Dict[int, str] = {
    0: "LOW",
    1: "NORMAL",
    2: "HIGH",
    3: "EXTREME",
}

CANDLE_CLASS_COL = "candle_class_id"
CANDLE_CLASS_CARDINALITY = 13
CANDLE_EMBED_DIM = 8

CANDLE_CLASS_NAMES: Dict[int, str] = {
    0: "FLAT_ZERO_RANGE",
    1: "DOJI_DRAGONFLY",
    2: "DOJI_GRAVESTONE",
    3: "DOJI_STANDARD",
    4: "MARUBOZU_BULL",
    5: "MARUBOZU_BEAR",
    6: "HAMMER_SHAPE",
    7: "INV_HAMMER_SHAPE",
    8: "SPINNING_TOP",
    9: "BELT_HOLD_BULL",
    10: "BELT_HOLD_BEAR",
    11: "STANDARD_BULL",
    12: "STANDARD_BEAR",
}

# Minimum test-set correlation for future_volatility before ONNX export.
MIN_EXPORT_VOL_CORR: Dict[str, float] = {
    "5m": 0.10,
    "15m": 0.10,
    "30m": 0.10,
    "1h": 0.08,
    "2h": 0.08,
}

PROMOTION_VOL_CORR: float = 0.15
PROMOTION_REGIME_ACCURACY: float = 0.35

EXPORT_QUALITY_DISCLAIMER = (
    "Sanity gates detect broken exports, not trading edge. "
    "Promotion tier targets are informational."
)

TRANSFORMER_METADATA_FILENAME = "metadata_transformer.json"
TRANSFORMER_FEATURE_CONFIG_FILENAME = "feature_config.json"


def compute_path_edge(mfe: float, mae: float) -> float:
    """Directional edge from predicted path asymmetry (MFE minus MAE).

    Alias of :func:`compute_long_edge` kept for train/serve telemetry compatibility.
    """
    return compute_long_edge(mfe, mae)


def compute_long_edge(mfe: float, mae: float) -> float:
    """Long-side path edge: upside (MFE) minus downside (MAE)."""
    return float(mfe) - float(mae)


def compute_short_edge(mfe: float, mae: float) -> float:
    """Short-side path edge: downside (MAE) minus upside (MFE)."""
    return float(mae) - float(mfe)


def path_favorable_adverse(
    mfe: float,
    mae: float,
    *,
    side: str,
) -> Tuple[float, float]:
    """Return (favorable_pct, adverse_pct) for bracket sizing.

    Labels are long-centric (MFE = upside, MAE = downside). For shorts, favorable
    excursion is downside (MAE) and adverse is upside (MFE).
    """
    s = str(side or "BUY").strip().upper()
    if s in ("SELL", "SHORT", "STRONG_SELL"):
        return float(mae), float(mfe)
    return float(mfe), float(mae)


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


def horizon_bars_for_wall_minutes(wall_minutes: int, resolution_minutes: int) -> int:
    """Convert wall-clock minutes to native-TF bar count."""
    return max(1, int(round(int(wall_minutes) / resolution_minutes)))


def label_horizon_bars_for_resolution(resolution_minutes: int) -> int:
    """Legacy helper: 8h wall-clock in bars for a TF grid."""
    return horizon_bars_for_wall_minutes(REFERENCE_LABEL_HORIZON_MINUTES, resolution_minutes)


def path_label_horizon_bars_for_resolution(resolution: str) -> int:
    """Path-label forward window in bars for a TF."""
    res = resolution.strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    minutes = RESOLUTION_MINUTES[res]
    wall = DEFAULT_PATH_LABEL_HORIZON_MINUTES.get(res, REFERENCE_LABEL_HORIZON_MINUTES)
    return horizon_bars_for_wall_minutes(wall, minutes)


def continuous_loss_weights_for_resolution(resolution: str) -> Tuple[float, ...]:
    """Per-head loss weights aligned with CONTINUOUS_LABEL_COLS (0 = no gradient)."""
    weights = dict(DEFAULT_CONTINUOUS_LOSS_WEIGHTS)
    return tuple(float(weights.get(col, 1.0)) for col in CONTINUOUS_LABEL_COLS)


def default_training_config(resolution: str) -> Dict[str, Any]:
    """Default Colab training config for a single TF model."""
    res = resolution.strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    minutes = RESOLUTION_MINUTES[res]
    path_horizon = path_label_horizon_bars_for_resolution(res)
    return {
        "symbol": "BTCUSD",
        "resolution": res,
        "resolution_minutes": minutes,
        "history_days": 900,
        "base_url": "https://api.india.delta.exchange",
        "atr_period": 14,
        "path_label_horizon_bars": path_horizon,
        "label_horizon_minutes_path": DEFAULT_PATH_LABEL_HORIZON_MINUTES.get(
            res, REFERENCE_LABEL_HORIZON_MINUTES
        ),
        "continuous_loss_weights": list(continuous_loss_weights_for_resolution(res)),
        "mae_floor_atr_mult": 0.25,
        "vol_regime_quantiles": [0.25, 0.5, 0.75],
        "window_len": 128,
        "stride": 8,
        "train_frac": 0.65,
        "val_frac": 0.15,
        "embargo_bars": path_horizon,
        "batch_size": 128,
        "epochs": 120,
        "lr": 1e-4,
        "d_model": 64,
        "nhead": 4,
        "num_layers": 2,
        "dropout": 0.25,
        "weight_decay": 1e-2,
        "early_stop_patience": 12,
        "early_stopping_enabled": True,
        "min_derivatives_coverage": 0.5,
        "derivatives_coverage_warn": 0.9,
        "min_export_vol_corr": MIN_EXPORT_VOL_CORR.get(res, 0.08),
        "default_threshold": 0.005,
        "seed": 42,
    }


def max_label_horizon_bars(
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
) -> int:
    """Maximum forward bars across all training labels."""
    return int(path_label_horizon_bars)


def scale_period(period: int, resolution_minutes: int, *, base_minutes: int = 5) -> int:
    """Scale indicator lookback to preserve wall-clock semantics across TFs."""
    return max(1, int(round(period * resolution_minutes / base_minutes)))
