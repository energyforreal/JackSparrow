"""Frozen constants for the v4 direction and pattern experiment.

Cost, take-profit, and stop-loss are not part of this contract.
"""

from __future__ import annotations

from research.forecast_30m.contract import (
    CALENDAR_COLUMNS,
    DIRECTION_NAMES,
    FEATURE_COLUMNS as BASE_FEATURE_COLUMNS,
    GATE4_LOGLOSS_LIFT,
    HORIZON_BARS,
    MINORITY_FLOOR,
    SEED,
    THETA_GRID,
    TREE_DEFAULTS,
)

SPEC_VERSION = "forecast-30m-h24-v4"
LABEL_VERSION = "forecast-30m-h24-labels-v4"
FEATURE_VERSION = "forecast-30m-h24-features-v4"
ALGORITHM = "xgb"
ENTRY = "next_open"

DEVELOPMENT_END_EXCLUSIVE = "2026-05-15T14:00:00+00:00"
SNAPSHOT_END = "2026-09-27T13:30:00+00:00"
ORIGINAL_SOURCE = "export/fusion_diagnostics/btcusd_30m_raw.parquet"

PATTERN_COLUMNS = (
    "doji",
    "hammer",
    "shooting_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "inside_bar",
    "close_broke_high_24",
    "close_broke_low_24",
    "consecutive_closes",
)
FEATURE_COLUMNS = BASE_FEATURE_COLUMNS + PATTERN_COLUMNS

# Trading-decision map from the direction class. Reporting only.
DECISION_BY_CLASS = {
    0: "sell",
    1: "hold",
    2: "buy",
}

DOJI_BODY_MAX = 0.10
HAMMER_WICK_MIN = 0.60
HAMMER_OPPOSITE_MAX = 0.15
CONSECUTIVE_CLIP = 12

__all__ = [
    "ALGORITHM",
    "CALENDAR_COLUMNS",
    "CONSECUTIVE_CLIP",
    "DECISION_BY_CLASS",
    "DEVELOPMENT_END_EXCLUSIVE",
    "DIRECTION_NAMES",
    "DOJI_BODY_MAX",
    "ENTRY",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "GATE4_LOGLOSS_LIFT",
    "HAMMER_OPPOSITE_MAX",
    "HAMMER_WICK_MIN",
    "HORIZON_BARS",
    "LABEL_VERSION",
    "MINORITY_FLOOR",
    "ORIGINAL_SOURCE",
    "PATTERN_COLUMNS",
    "SEED",
    "SNAPSHOT_END",
    "SPEC_VERSION",
    "THETA_GRID",
    "TREE_DEFAULTS",
]
