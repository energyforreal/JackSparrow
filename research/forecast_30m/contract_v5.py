"""Frozen constants for the v5 direction-policy experiment.

Promotion is after-cost expectancy. Log loss is not the gate.
"""

from __future__ import annotations

from research.forecast_30m.contract import (
    CALENDAR_COLUMNS,
    DIRECTION_NAMES,
    GATE5_MAX_DRAWDOWN,
    GATE5_MIN_TRADES,
    HORIZON_BARS,
    MINORITY_FLOOR,
    ROUND_TRIP_COST,
    SEED,
    THETA_GRID,
    THRESHOLD_GRID,
    TREE_DEFAULTS,
)
from research.forecast_30m.contract_v3 import (
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_BLOCK_BARS,
    BOOTSTRAP_DRAWS,
)
from research.forecast_30m.contract_v4 import (
    FEATURE_COLUMNS as FEATURE_COLUMNS_V4,
    PATTERN_COLUMNS,
)

SPEC_VERSION = "forecast-30m-h24-v5"
LABEL_VERSION = "forecast-30m-h24-labels-v5"
FEATURE_VERSION = "forecast-30m-h24-features-v5"
ALGORITHM = "xgb"
ENTRY = "next_open"

DEVELOPMENT_END_EXCLUSIVE = "2026-05-15T14:00:00+00:00"
SNAPSHOT_END = "2026-09-27T13:30:00+00:00"
ORIGINAL_SOURCE = "export/fusion_diagnostics/btcusd_30m_raw.parquet"
EXTENDED_SOURCE = "export/forecast_30m/v3/btcusd_30m_extended.parquet"

FEATURE_COLUMNS = FEATURE_COLUMNS_V4
PROBABILITY_FLOOR_GRID = THRESHOLD_GRID
HORIZON_MINUTES = HORIZON_BARS * 30

# Research report map. The live agent uppercases these.
DECISION_BY_CLASS = {
    0: "sell",
    1: "hold",
    2: "buy",
}
SIGNAL_BY_CLASS = {
    "BEARISH": "SELL",
    "NEUTRAL": "HOLD",
    "BULLISH": "BUY",
}

FORECAST_BUNDLE_DIR_NAME = "JackSparrow_Forecast_BTCUSD_30m"
FORECAST_DECISION_PATH = "forecast_30m"
FORECAST_SL_ATR_MULT = 2.0
FORECAST_TP_ATR_MULT = 3.0

__all__ = [
    "ALGORITHM",
    "BOOTSTRAP_ALPHA",
    "BOOTSTRAP_BLOCK_BARS",
    "BOOTSTRAP_DRAWS",
    "CALENDAR_COLUMNS",
    "DECISION_BY_CLASS",
    "DEVELOPMENT_END_EXCLUSIVE",
    "DIRECTION_NAMES",
    "ENTRY",
    "EXTENDED_SOURCE",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "FORECAST_BUNDLE_DIR_NAME",
    "FORECAST_DECISION_PATH",
    "FORECAST_SL_ATR_MULT",
    "FORECAST_TP_ATR_MULT",
    "GATE5_MAX_DRAWDOWN",
    "GATE5_MIN_TRADES",
    "HORIZON_BARS",
    "HORIZON_MINUTES",
    "LABEL_VERSION",
    "MINORITY_FLOOR",
    "ORIGINAL_SOURCE",
    "PATTERN_COLUMNS",
    "PROBABILITY_FLOOR_GRID",
    "ROUND_TRIP_COST",
    "SEED",
    "SIGNAL_BY_CLASS",
    "SNAPSHOT_END",
    "SPEC_VERSION",
    "THETA_GRID",
    "TREE_DEFAULTS",
]
