"""Frozen constants for the v3 confirmation experiment.

v2 constants stay in ``contract.py``. This module does not move the spent
holdout or enable orders.
"""

from __future__ import annotations

from research.forecast_30m.contract import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    GATE5_MAX_DRAWDOWN,
    GATE5_MIN_TRADES,
    HORIZON_BARS,
    MAX_AMBIGUOUS_SHARE,
    MAX_NO_SKILL_LOSS,
    MAX_PRECISION_GAP,
    MIN_PATH_RATE,
    ROUND_TRIP_COST,
    SEED,
    TREE_DEFAULTS,
)

SPEC_VERSION = "forecast-30m-h24-v3"
LABEL_VERSION = "forecast-30m-h24-labels-v3"
ALGORITHM = "xgb"
ENTRY = "next_open"

# Symmetric CUSUM on close-to-close log returns. Fixed before any new bars.
CUSUM_THRESHOLD = 0.02
# Barriers are fractions of the fill (next-bar open), not ATR multiples.
TP_PCT = 0.02
SL_PCT = 0.01
POLICY_THRESHOLD = 0.40
BREAKEVEN_PRECISION = (SL_PCT + ROUND_TRIP_COST) / (TP_PCT + SL_PCT)

# Original Phase 1 cut. Labels that touch this window are not fit or scored.
DEVELOPMENT_END_EXCLUSIVE = "2026-05-15T14:00:00+00:00"
SNAPSHOT_END = "2026-09-27T13:30:00+00:00"

BOOTSTRAP_BLOCK_BARS = 48
BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_ALPHA = 0.05

# Development-only ranking. Does not reopen confirmation or change barriers.
RANKING_BINS = 5
RANKING_VERSION = "forecast-30m-h24-ranking-v3"

ORIGINAL_SOURCE = "export/fusion_diagnostics/btcusd_30m_raw.parquet"
DELTA_HISTORY_URL = "https://api.india.delta.exchange/v2/history/candles"
DELTA_PAGE_SIZE = 500
DELTA_PAGE_DELAY_SECONDS = 0.4

__all__ = [
    "ALGORITHM",
    "BOOTSTRAP_ALPHA",
    "BOOTSTRAP_BLOCK_BARS",
    "BOOTSTRAP_DRAWS",
    "BREAKEVEN_PRECISION",
    "CUSUM_THRESHOLD",
    "DELTA_HISTORY_URL",
    "DELTA_PAGE_DELAY_SECONDS",
    "DELTA_PAGE_SIZE",
    "DEVELOPMENT_END_EXCLUSIVE",
    "ENTRY",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "GATE5_MAX_DRAWDOWN",
    "GATE5_MIN_TRADES",
    "HORIZON_BARS",
    "LABEL_VERSION",
    "MAX_AMBIGUOUS_SHARE",
    "MAX_NO_SKILL_LOSS",
    "MAX_PRECISION_GAP",
    "MIN_PATH_RATE",
    "ORIGINAL_SOURCE",
    "POLICY_THRESHOLD",
    "RANKING_BINS",
    "RANKING_VERSION",
    "ROUND_TRIP_COST",
    "SEED",
    "SL_PCT",
    "SNAPSHOT_END",
    "SPEC_VERSION",
    "TP_PCT",
    "TREE_DEFAULTS",
]
