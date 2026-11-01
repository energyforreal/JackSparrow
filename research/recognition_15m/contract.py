"""Frozen constants for the 15-minute recognition research track.

The live forecast path is a different package. Nothing here is an order.
"""

from __future__ import annotations

from feature_store.transformer_btcusd.contract import NATIVE_STRUCTURE_COLS
from research.forecast_30m.contract_v4 import PATTERN_COLUMNS

SPEC_VERSION = "recognition-15m-v2"
INSTRUMENT = "BTCUSD"
SOURCE_MINUTES = 5
BAR_MINUTES = 15
WINDOW_BARS = 48
PURGE_BARS = 48
ATR_PERIOD = 14
VOLUME_BASELINE = 48
TRAIN_FRACTION = 0.70
VAL_FRACTION = 0.15
TRAIN_STRIDE = 4
EVAL_STRIDE = 48
TCN_EPOCHS = 6
TCN_BATCH = 512
TCN_HIDDEN = 32
TCN_KERNEL = 3
TCN_DILATIONS = (1, 2, 4)
TCN_LEARNING_RATE = 1e-2
SEARCH_TRIALS = 30
SEARCH_EPOCHS = 20
SEARCH_PATIENCE = 4
FINAL_EPOCHS = 40
FINAL_PATIENCE = 6
DEVELOPMENT_FOLDS = 3
CORRELATION_FLAG = 0.5
SHAP_SAMPLE = 2000
HIDDEN_CHOICES = (32, 64, 128)
BATCH_CHOICES = (256, 512)
CLIP_CHOICES = (5.0, 10.0, 20.0, 40.0)
COLAB_OUTPUT_RELATIVE = "export/recognition_15m/colab/report.json"
XGB_ESTIMATORS = 40
XGB_MAX_DEPTH = 3
SEED = 7
POS_WEIGHT_CLIP = 20.0
ZZ_TAU = 1.5
ZZ_EPS_ATR = 0.15
PRIOR_TREND_BARS = 5
TREND_FLAT_BAND = 0.001

DOJI_BODY_MAX = 0.10
WICK_BODY_MULTIPLE = 2.0
WICK_OPPOSITE_MAX = 0.20
WICK_BODY_MIN = 0.05
RANGE_ATR_MIN = 0.50
MARUBOZU_BODY_MIN = 0.85
MARUBOZU_WICK_MAX = 0.08
ENGULF_BODY_ATR_MIN = 0.25
HARAMI_PRIOR_ATR_MIN = 0.40
TWEEZER_BODY_ATR_MIN = 0.20
TWEEZER_ATR_TOL = 0.15
STAR_LARGE_BODY = 0.55
STAR_SMALL_BODY = 0.30
SOLDIER_BODY_MIN = 0.50
SOLDIER_WICK_MAX = 0.25

SOURCE_RELATIVE = "export/fusion_diagnostics/btcusd_5m_raw.parquet"
OUTPUT_RELATIVE = "export/recognition_15m/metrics.json"

RAW_CHANNELS = (
    "open_atr",
    "high_atr",
    "low_atr",
    "close_atr",
    "volume_ratio",
)
ENGINEERED_CHANNELS = (
    "body_size_atr",
    "upper_wick_atr",
    "lower_wick_atr",
    "range_atr",
    "body_to_range",
    "upper_wick_to_range",
    "lower_wick_to_range",
    "close_location",
    "body_sign",
    "close_change_atr",
    "volume_ratio",
    "level_support_dist_atr",
    "level_resistance_dist_atr",
    "level_at_support",
    "level_at_resistance",
    "level_support_touches",
    "level_resistance_touches",
    "level_range_position",
)
ALLOWED_CHANNELS = frozenset(RAW_CHANNELS) | frozenset(ENGINEERED_CHANNELS)
LEVEL_LOOKBACK = 60
LEVEL_NEAR_ATR = 1.0
LEVEL_TOUCH_ATR = 0.5

GEOMETRIC_CLASSES = (
    "long_lower_wick",
    "long_upper_wick",
    "doji",
    "marubozu",
    "engulfing",
    "harami",
    "piercing_dark_cloud",
    "tweezer",
    "star",
    "soldiers_crows",
)
MARKET_STATES = (
    "uptrend",
    "downtrend",
    "range_bound",
    "transition",
    "indeterminate",
)
STRUCTURE_TAGS = ("hh_hl", "lh_ll", "mixed", "none")

RULE_CARD_COLUMNS = (
    "bar_time",
    "bar_index",
    "geometric_class",
    "conventional_name",
    "directional_bias",
    "context",
    "abstain",
)

FORBIDDEN_PREFIXES = ("cdl_", "chp_", "sr_", "tl_", "bo_")
FORECAST_LABEL_COLUMNS = (
    "y_direction",
    "forward_return_24",
    "forward_log_return_24",
    "long_path_code",
    "short_path_code",
    "long_tp_first_24",
    "short_tp_first_24",
    "tp_pct",
    "sl_pct",
    "neutral_band",
    "buy",
    "sell",
    "hold",
    "expectancy",
    "sharpe",
    "win_rate",
)
FORBIDDEN_EXACT = frozenset(
    tuple(PATTERN_COLUMNS)
    + tuple(NATIVE_STRUCTURE_COLS)
    + FORECAST_LABEL_COLUMNS
    + RULE_CARD_COLUMNS
    + GEOMETRIC_CLASSES
    + MARKET_STATES
    + STRUCTURE_TAGS
)

HEADS_NOT_TRAINED = ("B", "C", "D", "F", "G", "H")
RECOGNITION_BUNDLE_DIR_NAME = "JackSparrow_Recognition_BTCUSD_15m"
RECOGNITION_DECISION_PATH = "recognition_15m"
RECOGNITION_CHECKPOINT_NAME = "tcn_colab.pt"

__all__ = [
    "ALLOWED_CHANNELS",
    "ATR_PERIOD",
    "BAR_MINUTES",
    "ENGINEERED_CHANNELS",
    "LEVEL_LOOKBACK",
    "LEVEL_NEAR_ATR",
    "LEVEL_TOUCH_ATR",
    "EVAL_STRIDE",
    "FORBIDDEN_EXACT",
    "FORBIDDEN_PREFIXES",
    "GEOMETRIC_CLASSES",
    "HEADS_NOT_TRAINED",
    "RECOGNITION_BUNDLE_DIR_NAME",
    "RECOGNITION_CHECKPOINT_NAME",
    "RECOGNITION_DECISION_PATH",
    "MARKET_STATES",
    "OUTPUT_RELATIVE",
    "POS_WEIGHT_CLIP",
    "PURGE_BARS",
    "RAW_CHANNELS",
    "RULE_CARD_COLUMNS",
    "SEED",
    "SOURCE_RELATIVE",
    "SPEC_VERSION",
    "STRUCTURE_TAGS",
    "TCN_BATCH",
    "TCN_DILATIONS",
    "TCN_EPOCHS",
    "TCN_HIDDEN",
    "TCN_KERNEL",
    "BATCH_CHOICES",
    "CLIP_CHOICES",
    "COLAB_OUTPUT_RELATIVE",
    "CORRELATION_FLAG",
    "DEVELOPMENT_FOLDS",
    "FINAL_EPOCHS",
    "FINAL_PATIENCE",
    "HIDDEN_CHOICES",
    "SEARCH_EPOCHS",
    "SEARCH_PATIENCE",
    "SEARCH_TRIALS",
    "SHAP_SAMPLE",
    "TCN_LEARNING_RATE",
    "TRAIN_FRACTION",
    "TRAIN_STRIDE",
    "VAL_FRACTION",
    "VOLUME_BASELINE",
    "WINDOW_BARS",
    "XGB_ESTIMATORS",
    "XGB_MAX_DEPTH",
]
