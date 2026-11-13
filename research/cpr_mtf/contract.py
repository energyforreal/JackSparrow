"""Frozen constants for the CPR-MTF research track.

Nothing here is an order. Proposal tolerances are candidate-generation
parameters, not ground-truth labels.
"""

from __future__ import annotations

SPEC_VERSION = "cpr_mtf_v1"
INSTRUMENT = "BTCUSD"
SOURCE_MINUTES = 5
TIMEFRAMES = ("15m", "1h", "4h")
BAR_MINUTES = {"15m": 15, "1h": 60, "4h": 240}
SOURCE_BARS_PER_BUCKET = {"15m": 3, "1h": 12, "4h": 48}
TIMEFRAME_ID = {"15m": 0, "1h": 1, "4h": 2}

WINDOW_BARS = 192
SUFFIX_BARS = (48, 96, 192)
ATR_PERIOD = 14
VOLUME_BASELINE = 48
FIRST_FINITE_BAR = VOLUME_BASELINE - 1
ZZ_TAU = 1.5

PURGE_BARS = 384
TRAIN_FRACTION = 0.70
VAL_FRACTION = 0.15
TRAIN_STRIDE = 4
EVAL_EVENT_STRIDE = 384

MAX_PER_FAMILY = 2
MAX_CANDIDATES_PER_TIMEFRAME = 12
MAX_CANDIDATES = 36
PAIR_LIMIT = 32

SIMILAR_PRICE_ATR = 0.75
MIN_SEPARATION_BARS = 3
MIN_PATTERN_DEPTH_ATR = 1.0
HEAD_PROMINENCE_ATR = 0.75
IMPULSE_ATR_MIN = 3.0
FLAG_RETRACE_MAX = 0.55
SLOPE_FLAT_ATR = 0.015
PARALLEL_SLOPE_ATR = 0.01
CONVERGENCE_SLOPE_ATR = 0.01
TOUCH_TOL_ATR = 0.50
MIN_BOUNDARY_POINTS = 2
CUP_DEPTH_ATR = 2.0
MIN_CUP_SIDE_BARS = 5
HANDLE_RETRACE_MIN = 0.05
HANDLE_RETRACE_MAX = 0.50

BREAKOUT_BUFFER_ATR = 0.20
BREAKOUT_STRONG_ATR = 0.40
BREAKOUT_HORIZONS = (12, 24)
BREAKOUT_STATUSES = (
    "no_breakout",
    "upside_breakout",
    "downside_breakout",
    "invalidated",
    "ambiguous",
    "masked",
)

PATTERN_CLASSES = (
    "double",
    "triple",
    "head_and_shoulders",
    "flag",
    "pennant",
    "ascending_triangle",
    "descending_triangle",
    "symmetrical_triangle",
    "rising_wedge",
    "falling_wedge",
    "ascending_channel",
    "descending_channel",
    "rectangle",
    "broadening",
    "cup_and_handle",
)
DIRECTIONS = ("bullish", "bearish", "neutral")
MATURITY_STATES = ("developing", "mature", "confirmed", "invalidated")
GEOMETRY_KINDS = ("swing", "rounded_proxy")

SEQUENCE_CHANNELS = (
    "open_atr",
    "high_atr",
    "low_atr",
    "close_atr",
    "body_size_atr",
    "upper_wick_atr",
    "lower_wick_atr",
    "range_atr",
    "body_to_range",
    "close_location",
    "volume_ratio",
    "swing_high_flag",
    "swing_low_flag",
    "swing_high_prominence_atr",
    "swing_low_prominence_atr",
    "bars_since_confirmed_swing",
    "swing_high_slope",
    "swing_low_slope",
    "swing_range_atr",
    "price_position_in_swing_range",
)
MODEL_CANDIDATE_FEATURES = (
    "timeframe_id",
    "formation_width_bars",
    "formation_height_atr",
    "upper_boundary_slope",
    "lower_boundary_slope",
    "upper_boundary_distance_atr",
    "lower_boundary_distance_atr",
    "boundary_convergence_ratio",
    "boundary_divergence_ratio",
    "swing_high_count",
    "swing_low_count",
    "upper_boundary_touches",
    "lower_boundary_touches",
    "upper_boundary_error_atr",
    "lower_boundary_error_atr",
    "price_position_in_formation",
    "volume_contraction_ratio",
    "volume_expansion_ratio",
    "bars_since_last_interaction",
    "impulse_move_atr",
    "retracement_ratio",
    "formation_maturity_ratio",
)
PROPOSAL_ONLY_FIELDS = (
    "candidate_type_proposal",
    "candidate_quality_rule_score",
    "proposed_direction",
)

ANNOTATION_FIELDS = (
    "candidate_id",
    "identity",
    "direction",
    "maturity",
    "upper_boundary_atr",
    "lower_boundary_atr",
    "start_frac",
    "end_frac",
    "annotator",
    "notes",
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
    "breakout_status",
)
FORBIDDEN_EXACT = frozenset(
    FORECAST_LABEL_COLUMNS
    + PROPOSAL_ONLY_FIELDS
    + PATTERN_CLASSES
    + DIRECTIONS
    + MATURITY_STATES
    + BREAKOUT_STATUSES
    + ("reject", "identity", "maturity")
)

SOURCE_RELATIVE = "export/fusion_diagnostics/btcusd_5m_raw.parquet"
PREVIEW_RELATIVE = "export/cpr_mtf/preview"
AUDIT_RELATIVE = "export/cpr_mtf/audit.json"

__all__ = [
    "ANNOTATION_FIELDS",
    "ATR_PERIOD",
    "AUDIT_RELATIVE",
    "BAR_MINUTES",
    "BREAKOUT_BUFFER_ATR",
    "BREAKOUT_HORIZONS",
    "BREAKOUT_STATUSES",
    "BREAKOUT_STRONG_ATR",
    "CONVERGENCE_SLOPE_ATR",
    "CUP_DEPTH_ATR",
    "DIRECTIONS",
    "EVAL_EVENT_STRIDE",
    "FIRST_FINITE_BAR",
    "FLAG_RETRACE_MAX",
    "FORBIDDEN_EXACT",
    "FORBIDDEN_PREFIXES",
    "FORECAST_LABEL_COLUMNS",
    "GEOMETRY_KINDS",
    "HANDLE_RETRACE_MAX",
    "HANDLE_RETRACE_MIN",
    "HEAD_PROMINENCE_ATR",
    "IMPULSE_ATR_MIN",
    "INSTRUMENT",
    "MATURITY_STATES",
    "MAX_CANDIDATES",
    "MAX_CANDIDATES_PER_TIMEFRAME",
    "MAX_PER_FAMILY",
    "MIN_BOUNDARY_POINTS",
    "MIN_CUP_SIDE_BARS",
    "MIN_PATTERN_DEPTH_ATR",
    "MIN_SEPARATION_BARS",
    "MODEL_CANDIDATE_FEATURES",
    "PAIR_LIMIT",
    "PARALLEL_SLOPE_ATR",
    "PATTERN_CLASSES",
    "PREVIEW_RELATIVE",
    "PROPOSAL_ONLY_FIELDS",
    "PURGE_BARS",
    "SEQUENCE_CHANNELS",
    "SIMILAR_PRICE_ATR",
    "SLOPE_FLAT_ATR",
    "SOURCE_BARS_PER_BUCKET",
    "SOURCE_MINUTES",
    "SOURCE_RELATIVE",
    "SPEC_VERSION",
    "SUFFIX_BARS",
    "TIMEFRAMES",
    "TIMEFRAME_ID",
    "TOUCH_TOL_ATR",
    "TRAIN_FRACTION",
    "TRAIN_STRIDE",
    "VAL_FRACTION",
    "VOLUME_BASELINE",
    "WINDOW_BARS",
    "ZZ_TAU",
]
