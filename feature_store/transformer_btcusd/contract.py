"""Constants shared between per-TF Colab training and agent inference."""

from __future__ import annotations

from typing import Any, Dict, Tuple

# Bump when FEATURE_COLS, label heads, or ONNX outputs change (requires retrain).
FEATURE_CONTRACT_VERSION_V6 = "transformer_btcusd_per_tf_features_v6"
FEATURE_CONTRACT_VERSION_V7 = "transformer_btcusd_per_tf_features_v7"
FEATURE_CONTRACT_VERSION_V8 = "transformer_btcusd_per_tf_features_v8"
FEATURE_CONTRACT_VERSION_V9 = "transformer_btcusd_per_tf_features_v9"
FEATURE_CONTRACT_VERSION_V10 = "transformer_btcusd_mtf_fusion_v10"
# Live per-TF bundles remain v9. The fused model uses V10.
FEATURE_CONTRACT_VERSION = FEATURE_CONTRACT_VERSION_V9

SUPPORTED_RESOLUTIONS: Tuple[str, ...] = ("5m", "15m", "30m", "1h", "2h")
FUSION_INPUT_RESOLUTIONS: Tuple[str, ...] = ("5m", "10m", "30m", "1h", "2h")
FUSION_BUNDLE_DIR_NAME = "JackSparrow_Transformer_BTCUSD_mtf_fusion"
FUSION_MODEL_FAMILY = "jacksparrow_transformer_btcusd_mtf_fusion"
FUSION_ONNX_FILENAME = "btcusd_mtf_fusion.onnx"
FUSION_WINDOW_LEN: int = 64
FUSION_EMBARGO_BARS: int = 24

RESOLUTION_MINUTES: Dict[str, int] = {
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
}

TF_KEYS: Tuple[str, ...] = tuple(f"tf_{r}" for r in SUPPORTED_RESOLUTIONS)

HTF_SOURCE_TFS: Tuple[str, ...] = ("15m", "30m", "1h", "2h")
HTF_FEATURE_FIELDS: Tuple[str, ...] = (
    "structure_bias",
    "trend_efficiency",
    "ema21_slope_atr",
    "dist_support_atr",
    "dist_resistance_atr",
    "range_width_atr",
)

NATIVE_STRUCTURE_COLS: Tuple[str, ...] = (
    "hh_count",
    "hl_count",
    "lh_count",
    "ll_count",
    "structure_bias",
    "last_swing_dir",
    "bars_since_swing",
    "swing_amp_atr",
    "unconfirmed_ext_atr",
    "trend_efficiency",
    "displacement_atr",
    "pct_with_trend",
    "price_vs_ema9_atr",
    "price_vs_ema21_atr",
    "price_vs_ema50_atr",
    "price_vs_ema200_atr",
    "ema9_vs_21_atr",
    "ema21_vs_50_atr",
    "ema50_vs_200_atr",
    "ema21_slope_atr",
    "ema50_slope_atr",
    "dist_to_support_atr",
    "dist_to_resistance_atr",
    "support_touch_count",
    "resistance_touch_count",
    "range_width_atr",
    "range_width_pctile",
    "atr_contraction",
    "breakout_size_atr",
    "breakout_vol_ratio",
    "pre_breakout_comp",
    "bars_since_breakout",
    "retest_dist_atr",
    "failed_break",
    "peak_diff_atr",
    "trough_diff_atr",
    "peak_sep_bars",
    "trough_sep_bars",
    "dist_neck_atr",
    "high_slope_atr",
    "low_slope_atr",
    "convergence",
    "width_now_atr",
    "pole_disp_atr",
    "flag_width_atr",
    "flag_slope_atr",
)

HTF_STRUCTURE_COLS: Tuple[str, ...] = tuple(
    f"htf_{tf}_{field}" for tf in HTF_SOURCE_TFS for field in HTF_FEATURE_FIELDS
)

_V4_FEATURE_COLS: Tuple[str, ...] = (
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
    "close_loc",
    "range_atr",
    "body_atr",
    "gap_atr",
    "inside_bar",
    "outside_bar",
    "engulf_score",
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

# Native all-TF continuous columns (v4 plus causal structure/geometry).
FEATURE_COLS: Tuple[str, ...] = _V4_FEATURE_COLS + NATIVE_STRUCTURE_COLS

PATH_LABEL_COLS: Tuple[str, ...] = (
    "mfe",
    "mae",
    "future_volatility",
    "trend_strength",
    "drawdown_before_mfe",
    "future_oi_change_pct",
    "future_volume_change_pct",
    "candle_follow_through_atr",
    "structure_delta",
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
    "candle_follow_through_atr": 0.5,
    "structure_delta": 0.5,
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

# Discrete training/inference columns (not continuous ONNX heads).
STRUCTURE_OUTCOME_COL = "future_structure_outcome"
FUTURE_CANDLE_COL = "future_candle_class"
STRUCTURE_OUTCOME_CARDINALITY = 6
N_AUX_CLASS_HEADS = 3  # vol regime + structure outcome + next-bar candle

# v7 next-candle structure (kept for legacy 5m ONNX decode).
NEXT_DIRECTION_COL = "next_direction"
NEXT_BODY_COL = "next_body"
NEXT_WICK_COL = "next_wick"
NEXT_RANGE_COL = "next_range"
CHART_PATTERN_COL = "chart_pattern_id"
VOLUME_STATE_COL = "volume_state"
VOLUME_CONFIRMS_COL = "volume_confirms"
PATTERN_ACTIVE_COL = "pattern_active"
SAMPLE_WEIGHT_COL = "sample_weight"

# v8 wall-clock behavior packets on the 5m grid (bars).
HORIZON_SPECS: Tuple[Tuple[str, int], ...] = (
    ("h5m", 1),
    ("h10m", 2),
    ("h15m", 3),
    ("h30m", 6),
    ("h1h", 12),
    ("h2h", 24),
)
HORIZON_KEYS: Tuple[str, ...] = tuple(key for key, _ in HORIZON_SPECS)
HORIZON_BARS_5M: Tuple[int, ...] = tuple(bars for _, bars in HORIZON_SPECS)
N_HORIZONS: int = len(HORIZON_SPECS)
MAX_V8_HORIZON_BARS: int = max(HORIZON_BARS_5M)
HORIZON_CONTINUOUS_FIELDS: Tuple[str, ...] = ("mfe", "mae", "vol", "trend_strength")
HORIZON_DIR_COLS: Tuple[str, ...] = tuple(f"{key}_dir" for key in HORIZON_KEYS)
HORIZON_STRUCTURE_COLS: Tuple[str, ...] = tuple(
    f"{key}_structure" for key in HORIZON_KEYS
)
V8_CONTINUOUS_LABEL_COLS: Tuple[str, ...] = tuple(
    f"{key}_{field}"
    for key in HORIZON_KEYS
    for field in HORIZON_CONTINUOUS_FIELDS
)
HORIZON_DIR_COLS_V7: Tuple[str, ...] = (
    "horizon_t1_dir",
    "horizon_t3_dir",
    "horizon_t6_dir",
    "horizon_t12_dir",
    "horizon_t24_dir",
)

NEXT_DIRECTION_CARDINALITY_V8 = 3
NEXT_DIRECTION_CARDINALITY = 5
NEXT_BODY_CARDINALITY = 3
NEXT_WICK_CARDINALITY = 4
NEXT_RANGE_CARDINALITY = 3
VOLUME_STATE_CARDINALITY = 3
CHART_PATTERN_CARDINALITY = 9

NEXT_DIRECTION_NAMES_V8: Dict[int, str] = {0: "BEARISH", 1: "NEUTRAL", 2: "BULLISH"}
NEXT_DIRECTION_NAMES: Dict[int, str] = {
    0: "STRONG_DOWN",
    1: "DOWN",
    2: "NEUTRAL",
    3: "UP",
    4: "STRONG_UP",
}
BULLISH_DIRECTION_NAMES = frozenset({"UP", "STRONG_UP", "BULLISH"})
BEARISH_DIRECTION_NAMES = frozenset({"DOWN", "STRONG_DOWN", "BEARISH"})
NEUTRAL_DIRECTION_NAMES = frozenset({"NEUTRAL"})
NEXT_BODY_NAMES: Dict[int, str] = {0: "SMALL", 1: "MEDIUM", 2: "LARGE"}
NEXT_WICK_NAMES: Dict[int, str] = {
    0: "BALANCED",
    1: "UPPER_REJECTION",
    2: "LOWER_REJECTION",
    3: "BOTH_REJECTION",
}
NEXT_RANGE_NAMES: Dict[int, str] = {0: "COMPRESSED", 1: "NORMAL", 2: "EXPANDED"}
VOLUME_STATE_NAMES: Dict[int, str] = {0: "DRY", 1: "NORMAL", 2: "EXPANSION"}
CHART_PATTERN_NAMES: Dict[int, str] = {
    0: "NONE",
    1: "FLAG_BULL",
    2: "FLAG_BEAR",
    3: "TRIANGLE",
    4: "DOUBLE_TOP",
    5: "DOUBLE_BOTTOM",
    6: "CHANNEL",
    7: "BREAKOUT",
    8: "FAILED_BREAK",
}

VOL_Z_EXPANSION = 0.5
VOL_Z_DRY = -0.5
BREAKOUT_VOL_CONFIRM = 1.2
HORIZON_DIR_ATR_WEAK = 0.5
HORIZON_DIR_ATR_STRONG = 2.0
HORIZON_DIR_ATR_DEADZONE = HORIZON_DIR_ATR_WEAK

V7_STRUCTURE_LOSS_WEIGHTS: Dict[str, float] = {
    "direction": 1.0,
    "body": 0.5,
    "wick": 0.5,
    "range": 0.5,
    "pattern": 0.5,
    "path": 1.0,
    "volume_state": 0.25,
    "pattern_validates": 0.25,
    "horizon": 0.35,
}

V8_STRUCTURE_LOSS_WEIGHTS: Dict[str, float] = {
    "path": 1.0,
    "direction": 1.0,
    "structure": 0.5,
    "volume_state": 0.25,
}
V9_STRUCTURE_LOSS_WEIGHTS: Dict[str, float] = {
    "path": 1.0,
    "direction": 1.0,
    "structure": 0.5,
    "volume_state": 0.25,
    "pattern": 0.25,
}

V7_CONTINUOUS_LOSS_WEIGHTS: Dict[str, float] = {
    "mfe": 0.5,
    "mae": 0.5,
    "future_volatility": 1.0,
    "trend_strength": 0.5,
    "drawdown_before_mfe": 0.5,
    "future_oi_change_pct": 0.25,
    "future_volume_change_pct": 0.25,
    "candle_follow_through_atr": 0.5,
    "structure_delta": 0.5,
}

STRUCTURE_OUTCOME_NAMES: Dict[int, str] = {
    0: "RANGE",
    1: "CONTINUATION_LONG",
    2: "CONTINUATION_SHORT",
    3: "BREAKOUT",
    4: "FAILED_BREAK",
    5: "REVERSAL",
}

ONNX_OUTPUT_NAMES_V6: Tuple[str, ...] = (
    "continuous_pred",
    "regime_logits",
    "structure_outcome_logits",
    "future_candle_logits",
)
# Live 15m–2h bundles still export v6 heads. 5m research is v8.
ONNX_OUTPUT_NAMES: Tuple[str, ...] = ONNX_OUTPUT_NAMES_V6

ONNX_OUTPUT_NAMES_V7_BASE: Tuple[str, ...] = (
    "next_direction_logits",
    "next_body_logits",
    "next_wick_logits",
    "next_range_logits",
    "next_pattern_logits",
    "continuous_pred",
    "volume_state_logits",
    "pattern_validates_logit",
)
ONNX_OUTPUT_NAMES_V7_HORIZONS: Tuple[str, ...] = (
    "horizon_t3_dir_logits",
    "horizon_t6_dir_logits",
    "horizon_t12_dir_logits",
    "horizon_t24_dir_logits",
)
ONNX_OUTPUT_NAMES_V7: Tuple[str, ...] = (
    ONNX_OUTPUT_NAMES_V7_BASE + ONNX_OUTPUT_NAMES_V7_HORIZONS
)
ONNX_OUTPUT_NAMES_V8_DIR: Tuple[str, ...] = tuple(
    f"{key}_dir_logits" for key in HORIZON_KEYS
)
ONNX_OUTPUT_NAMES_V8_STRUCTURE: Tuple[str, ...] = tuple(
    f"{key}_structure_logits" for key in HORIZON_KEYS
)
ONNX_OUTPUT_NAMES_V8: Tuple[str, ...] = (
    ONNX_OUTPUT_NAMES_V8_DIR
    + ONNX_OUTPUT_NAMES_V8_STRUCTURE
    + ("continuous_pred", "volume_state_logits")
)
ONNX_OUTPUT_NAMES_V9: Tuple[str, ...] = ONNX_OUTPUT_NAMES_V8 + ("chart_pattern_logits",)

# v10 fused multi-TF model: 3-class position heads, no MFE/MAE.
FUSION_HORIZON_SPECS: Tuple[Tuple[str, int], ...] = (
    ("h10m", 2),
    ("h30m", 6),
    ("h1h", 12),
    ("h2h", 24),
)
FUSION_HORIZON_KEYS: Tuple[str, ...] = tuple(key for key, _ in FUSION_HORIZON_SPECS)
FUSION_HORIZON_BARS_5M: Tuple[int, ...] = tuple(bars for _, bars in FUSION_HORIZON_SPECS)
N_FUSION_HORIZONS: int = len(FUSION_HORIZON_SPECS)
MAX_FUSION_HORIZON_BARS: int = max(FUSION_HORIZON_BARS_5M)
FUSION_DIR_COLS: Tuple[str, ...] = tuple(f"{key}_dir" for key in FUSION_HORIZON_KEYS)
FUSION_DIRECTION_CARDINALITY = 3
FUSION_DIRECTION_NAMES: Dict[int, str] = {0: "BEAR", 1: "NEUTRAL", 2: "BULL"}
FUSION_POSITION_LONG = "LONG"
FUSION_POSITION_SHORT = "SHORT"
FUSION_POSITION_HOLD = "HOLD"
FUSION_GRADE_HIGH = "HIGH"
FUSION_GRADE_MEDIUM = "MEDIUM"
FUSION_GRADE_LOW = "LOW"
FUSION_HIGH_BALANCED_ACC = 0.45
FUSION_HIGH_MAX_ECE = 0.08
FUSION_MEDIUM_BALANCED_ACC = 0.40
FUSION_MIN_PROBABILITY = 0.55
ONNX_OUTPUT_NAMES_V10: Tuple[str, ...] = tuple(
    f"{key}_dir_logits" for key in FUSION_HORIZON_KEYS
) + ("tf_fusion_logits",)
FUSION_DURATION_ATR_MULT: Dict[str, Tuple[float, float]] = {
    "h10m": (0.75, 1.0),
    "h30m": (1.0, 1.5),
    "h1h": (1.5, 2.25),
    "h2h": (2.0, 3.0),
}
FUSION_HORIZON_MINUTES: Dict[str, int] = {
    "h10m": 10,
    "h30m": 30,
    "h1h": 60,
    "h2h": 120,
}

# Next-bar candle families for 5m timing (not model classes).
CANDLE_FAMILY_DOJI = frozenset({0, 1, 2, 3, 8})
CANDLE_FAMILY_BULL = frozenset({4, 6, 9, 11})
CANDLE_FAMILY_BEAR = frozenset({5, 7, 10, 12})

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


def candle_family_from_class(class_id: int) -> str:
    """Map a candle class id to bull / bear / doji for timing modifiers."""
    cid = int(class_id)
    if cid in CANDLE_FAMILY_BULL:
        return "bull"
    if cid in CANDLE_FAMILY_BEAR:
        return "bear"
    return "doji"


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
    if res == "mtf_fusion":
        return FUSION_MODEL_FAMILY
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    return f"jacksparrow_transformer_btcusd_{res}"


def onnx_filename_for_resolution(resolution: str) -> str:
    res = resolution.strip().lower()
    if res == "mtf_fusion":
        return FUSION_ONNX_FILENAME
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    return f"btcusd_{res}_transformer.onnx"


def bundle_dir_name(resolution: str) -> str:
    res = resolution.strip().lower()
    if res == "mtf_fusion":
        return FUSION_BUNDLE_DIR_NAME
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


def feature_cols_for_resolution(resolution: str) -> Tuple[str, ...]:
    """Continuous feature columns for a TF bundle (5m appends closed HTF context)."""
    res = resolution.strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    if res == "5m":
        return FEATURE_COLS + HTF_STRUCTURE_COLS
    return FEATURE_COLS


def fusion_native_feature_cols() -> Tuple[str, ...]:
    """Native-TF columns for the fused model (no resampled HTF context)."""
    return FEATURE_COLS


def v7_feature_cols_for_resolution(resolution: str) -> Tuple[str, ...]:
    """Input columns: native features plus causal chart_pattern_id."""
    return feature_cols_for_resolution(resolution) + (CHART_PATTERN_COL,)


def v8_feature_cols_for_resolution(resolution: str) -> Tuple[str, ...]:
    """v8 5m input columns (native features plus causal chart_pattern_id)."""
    return v7_feature_cols_for_resolution(resolution)


def v9_feature_cols_for_resolution(resolution: str) -> Tuple[str, ...]:
    """v9 5m input columns: geometry only; chart_pattern_id is a target head."""
    return feature_cols_for_resolution(resolution)


def onnx_output_names_for_contract(
    contract_version: str,
    *,
    resolution: str = "5m",
) -> Tuple[str, ...]:
    """ONNX head names for a bundle contract."""
    ver = str(contract_version or "").strip()
    res = resolution.strip().lower()
    if ver == FEATURE_CONTRACT_VERSION_V10 or res == "mtf_fusion":
        return ONNX_OUTPUT_NAMES_V10
    if ver in (FEATURE_CONTRACT_VERSION, FEATURE_CONTRACT_VERSION_V9):
        if res == "5m":
            return ONNX_OUTPUT_NAMES_V9
        return ONNX_OUTPUT_NAMES_V6
    if ver == FEATURE_CONTRACT_VERSION_V8:
        if res == "5m":
            return ONNX_OUTPUT_NAMES_V8
        return ONNX_OUTPUT_NAMES_V6
    if ver == FEATURE_CONTRACT_VERSION_V7:
        if res == "5m":
            return ONNX_OUTPUT_NAMES_V7
        return ONNX_OUTPUT_NAMES_V7_BASE
    return ONNX_OUTPUT_NAMES_V6


def v8_future_leak_cols() -> frozenset:
    """Label/target columns that must never appear in 5m v8 model inputs."""
    leaked = set(V8_CONTINUOUS_LABEL_COLS)
    leaked.update(HORIZON_DIR_COLS)
    leaked.update(HORIZON_STRUCTURE_COLS)
    leaked.update(
        {
            VOLUME_STATE_COL,
            NEXT_DIRECTION_COL,
            NEXT_BODY_COL,
            NEXT_WICK_COL,
            NEXT_RANGE_COL,
            FUTURE_CANDLE_COL,
            "mfe",
            "mae",
            "future_volatility",
            "pattern_validates",
            *HORIZON_DIR_COLS_V7,
        }
    )
    return frozenset(leaked)


def expected_direction_from_chart_pattern(pattern_id: int) -> int:
    """Map chart pattern to expected next-candle direction (0/1/2). Neutral if none."""
    pid = int(pattern_id)
    if pid in (1, 5, 7):  # FLAG_BULL, DOUBLE_BOTTOM, BREAKOUT (unsigned handled elsewhere)
        return 2
    if pid in (2, 4, 8):  # FLAG_BEAR, DOUBLE_TOP, FAILED_BREAK
        return 0
    return 1


def default_research_config() -> Dict[str, Any]:
    """Colab research-pipeline defaults (5m multi-horizon path)."""
    return {
        "symbol": "BTCUSD",
        "resolution": "5m",
        "resolution_minutes": 5,
        "base_timeframe": "5m",
        "context_timeframes": ["15m", "30m", "1h", "2h"],
        "sequence_length": 64,
        "prediction_horizon": 1,
        "horizon_bars": list(HORIZON_BARS_5M),
        "train_ratio": 0.70,
        "validation_ratio": 0.15,
        "test_ratio": 0.15,
        "batch_size": 256,
        "epochs": 50,
        "learning_rate": 1e-4,
        "weight_decay": 1e-4,
        "dropout": 0.15,
        "early_stopping_patience": 8,
        "seed": 42,
        "d_model": 64,
        "nhead": 4,
        "num_layers": 2,
        "stride": 4,
        "scaler_mode": "train_fit",
        "gate_chart_volume": False,
        "path_label_horizon_bars": MAX_V8_HORIZON_BARS,
        "embargo_bars": MAX_V8_HORIZON_BARS,
        "mae_floor_atr_mult": 0.25,
        "atr_period": 14,
        "history_days": 900,
        "base_url": "https://api.india.delta.exchange",
        "loss_weights": dict(V9_STRUCTURE_LOSS_WEIGHTS),
        "run_optuna": False,
        "optuna_trials": 0,
        "run_shap": False,
        "run_ablations": False,
        "run_walk_forward": False,
        "walk_forward_folds": 3,
    }


def default_fusion_training_config() -> Dict[str, Any]:
    """Defaults for the single multi-TF fusion trainer."""
    return {
        "symbol": "BTCUSD",
        "resolutions": list(FUSION_INPUT_RESOLUTIONS),
        "horizon_keys": list(FUSION_HORIZON_KEYS),
        "horizon_bars": list(FUSION_HORIZON_BARS_5M),
        "window_len": FUSION_WINDOW_LEN,
        "stride": 4,
        "train_frac": 0.70,
        "val_frac": 0.15,
        "embargo_bars": FUSION_EMBARGO_BARS,
        "batch_size": 64,
        "epochs": 40,
        "lr": 1e-4,
        "weight_decay": 1e-4,
        "dropout": 0.15,
        "d_model": 64,
        "nhead": 4,
        "num_layers": 2,
        "early_stop_patience": 8,
        "seed": 42,
        "history_days": 900,
        "base_url": "https://api.india.delta.exchange",
        "atr_period": 14,
        "run_optuna": False,
        "optuna_trials": 0,
        "walk_forward_folds": 3,
        "walk_forward_embargo": FUSION_EMBARGO_BARS,
        "min_probability": FUSION_MIN_PROBABILITY,
        "high_balanced_acc": FUSION_HIGH_BALANCED_ACC,
        "high_max_ece": FUSION_HIGH_MAX_ECE,
        "medium_balanced_acc": FUSION_MEDIUM_BALANCED_ACC,
    }


def ablation_feature_groups(resolution: str = "5m") -> Dict[str, Tuple[str, ...]]:
    """Nested feature sets A-F for out-of-sample ablation."""
    all_cols = v9_feature_cols_for_resolution(resolution)
    ohlcv = ("ret_1", "rv_16", "rv_96", "hour_sin", "hour_cos", "dow_sin", "dow_cos")
    geometry = ohlcv + (
        "body_ratio",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "close_loc",
        "range_atr",
        "body_atr",
        "gap_atr",
        "inside_bar",
        "outside_bar",
        "engulf_score",
    )
    trend = geometry + (
        "ema50_dist_pct",
        "macd_hist",
        "rsi_14",
        "adx_14",
        "price_vs_ema9_atr",
        "price_vs_ema21_atr",
        "price_vs_ema50_atr",
        "price_vs_ema200_atr",
        "ema9_vs_21_atr",
        "ema21_vs_50_atr",
        "ema50_vs_200_atr",
        "ema21_slope_atr",
        "ema50_slope_atr",
        "trend_efficiency",
        "displacement_atr",
        "pct_with_trend",
    )
    structure = trend + (
        "hh_count",
        "hl_count",
        "lh_count",
        "ll_count",
        "structure_bias",
        "last_swing_dir",
        "bars_since_swing",
        "swing_amp_atr",
        "dist_to_support_atr",
        "dist_to_resistance_atr",
        "support_touch_count",
        "resistance_touch_count",
        "range_width_atr",
        "dist_to_resistance_pct",
        "dist_to_support_pct",
    )
    chart = structure + (
        "peak_diff_atr",
        "trough_diff_atr",
        "peak_sep_bars",
        "trough_sep_bars",
        "dist_neck_atr",
        "high_slope_atr",
        "low_slope_atr",
        "convergence",
        "width_now_atr",
        "pole_disp_atr",
        "flag_width_atr",
        "flag_slope_atr",
        "breakout_size_atr",
        "breakout_vol_ratio",
        "pre_breakout_comp",
        "bars_since_breakout",
        "retest_dist_atr",
        "failed_break",
    )
    return {
        "A": tuple(c for c in ohlcv if c in all_cols),
        "B": tuple(c for c in geometry if c in all_cols),
        "C": tuple(c for c in trend if c in all_cols),
        "D": tuple(c for c in structure if c in all_cols),
        "E": tuple(c for c in chart if c in all_cols),
        "F": all_cols,
    }
