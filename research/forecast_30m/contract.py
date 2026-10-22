"""Frozen constants for the 30-minute, 24-bar research line.

Numeric label choices that depend on the development sample are not stored
here. The selection rules that produce them are.
"""

from __future__ import annotations

SPEC_VERSION = "forecast-30m-h24-v2"
LABEL_VERSION = "forecast-30m-h24-labels-v2"
FEATURE_VERSION = "forecast-30m-h24-features-v1"

HORIZON_BARS = 24
ATR_PERIOD = 14
PURGE_BARS = 24
SEED = 42
WALKS = 4
CALIBRATION_FRACTION = 0.15
OPTUNA_TRIALS = 8
# Default trees only, until one of them passes the economic gate.
TUNE_ENABLED = False
MIN_PHASE_ROWS = 20
MINORITY_FLOOR = 0.15
MIN_PATH_RATE = 0.10
MAX_AMBIGUOUS_SHARE = 0.05
MIN_TP_COST_RATIO = 4.0
# Median neutral band must cover 1.5 round trips, so a directional label
# is a move larger than the configured cost.
MIN_NEUTRAL_COST_MULTIPLE = 1.5
# Unconditional barrier expectancy must be at least this close to flat.
MAX_NO_SKILL_LOSS = 0.0005
# Empirical TP-first rate must sit within this distance of breakeven precision.
MAX_PRECISION_GAP = 0.05
# Direction log loss must beat the class prior by this much on a fold.
GATE4_LOGLOSS_LIFT = 0.01
# Return MAE must beat a zero forecast by this fraction on a fold.
GATE4_MAE_LIFT = 0.01
ABLATION_MIN_DELTA = {
    "direction": 0.01,
    "return": 0.0001,
    "long_tp": 0.0005,
    "short_tp": 0.0005,
}

# agent/core/config.py defaults. Two legs, each taker fee plus slippage.
TAKER_FEE_RATE = 0.0005
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2.0 * (TAKER_FEE_RATE + SLIPPAGE_BPS / 10_000.0)
COST_STRESS = (1.0, 1.5, 2.0)

THETA_GRID = (0.25, 0.40, 0.50, 0.75, 1.00)
BARRIER_GRID = (
    (1.0, 1.0),
    (1.5, 1.0),
    (2.0, 1.0),
    (2.0, 1.5),
    (2.0, 2.0),
    (3.0, 1.5),
    (3.0, 2.0),
    (3.0, 3.0),
)
THRESHOLD_GRID = (0.35, 0.45, 0.55, 0.65, 0.75)

GATE5_MIN_TRADES = 20
GATE5_MAX_DRAWDOWN = -0.15

BEARISH = 0
NEUTRAL = 1
BULLISH = 2
DIRECTION_NAMES = ("BEARISH", "NEUTRAL", "BULLISH")

TP_FIRST = 0
SL_FIRST = 1
EXPIRY = 2
AMBIGUOUS = 3
UNLABELED = -1
PATH_NAMES = ("TP_FIRST", "SL_FIRST", "EXPIRY", "AMBIGUOUS")

FEATURE_COLUMNS = (
    "return_1",
    "return_6",
    "return_12",
    "return_24",
    "ma_distance_20",
    "ma_slope_20",
    "rsi_14",
    "atr_pct_14",
    "vol_ratio_12_48",
    "candle_body",
    "upper_wick",
    "lower_wick",
    "close_location",
    "volume_ratio_24",
    "dist_high_24",
    "dist_low_24",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)
CALENDAR_COLUMNS = ("hour_sin", "hour_cos", "dow_sin", "dow_cos")

TREE_DEFAULTS = {
    "n_estimators": 160,
    "max_depth": 4,
    "learning_rate": 0.05,
    "min_child_weight": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
}
