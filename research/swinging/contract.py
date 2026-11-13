"""Frozen constants for the swinging research track.

Nothing here enables an order. Cost figures match the forecast v5 round trip
and add an explicit funding term at simulation time.
"""

from __future__ import annotations

SPEC_VERSION = "swinging-v1"
SYMBOL = "BTCUSD"
RESOLUTIONS = ("5m", "15m", "1h", "4h")
BAR_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
BAR_SECONDS = {name: minutes * 60 for name, minutes in BAR_MINUTES.items()}

DELTA_BASE_URL = "https://api.india.delta.exchange"
DELTA_CANDLES_URL = f"{DELTA_BASE_URL}/v2/history/candles"
PAGE_BARS = 2000
HISTORY_START = "2018-01-01T00:00:00+00:00"
COLAB_DATA_ROOT = "/content/JackSparrow/data"
COLAB_REPO_ROOT = "/content/JackSparrow"

TAKER_FEE_RATE = 0.0005
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2.0 * (TAKER_FEE_RATE + SLIPPAGE_BPS / 10_000.0)
BREAKEVEN_BAND = 0.0005

STOP_ATR_MULT = 1.5
TAKE_PROFIT_ATR_MULT = 2.5
MAX_HOLD_BARS = {"5m": 48, "15m": 32, "1h": 24, "4h": 12}
BREAKOUT_LOOKBACK = 20
WARMUP_BARS = 30
NEUTRAL_STRIDE = 8
ACCEPT_SCORE = 0.55
REJECT_SCORE = 0.35

SETUP_TYPES = (
    "long_breakout",
    "short_breakdown",
    "breakout_retest",
    "support_bounce",
    "resistance_rejection",
    "reversal",
    "trend_continuation",
    "candlestick",
    "chart_pattern",
)
DIRECTIONS = ("long", "short", "neutral")
CANDIDATE_STATUSES = ("accepted", "rejected", "neutral")
OUTCOME_LABELS = ("win", "loss", "breakeven", "expiry")
REGIME_LABELS = (
    "trending",
    "ranging",
    "high_volatility",
    "low_volatility",
    "transition",
)
SR_LABELS = ("bounce", "rejection", "breakout", "failed_breakout")
STRATEGIES = ("algorithm_only", "ml_only", "hybrid")

SERIES_KINDS = ("ohlcv", "mark", "funding", "oi")
DERIVATIVE_PREFIX = {"mark": "MARK:", "funding": "FUNDING:", "oi": "OI:"}

SWING_COLUMNS = (
    "swing_high_dist_atr",
    "swing_low_dist_atr",
    "bars_since_swing_high",
    "bars_since_swing_low",
)

# Labels and trade results. These must never appear in a feature snapshot.
FORBIDDEN_FEATURE_COLUMNS = frozenset(
    {
        "outcome_label",
        "sr_label",
        "regime_target",
        "net_return",
        "gross_return",
        "mfe",
        "mae",
        "exit_price",
        "exit_timestamp",
        "funding_pnl",
        "breakout_status",
        "orders_enabled",
    }
)

SETUP_META_COLUMNS = (
    "setup_id",
    "signal_timestamp",
    "bar_index",
    "direction",
    "setup_type",
    "timeframe",
    "algorithmic_score",
    "reasoning",
    "invalidation",
    "status",
)

OUTCOME_COLUMNS = (
    "entry_timestamp",
    "entry_price",
    "stop_price",
    "take_profit_price",
    "exit_timestamp",
    "exit_price",
    "exit_reason",
    "holding_seconds",
    "mfe",
    "mae",
    "gross_return",
    "fee_return",
    "slippage_return",
    "funding_pnl",
    "missing_funding",
    "net_return",
    "outcome_label",
    "simulated",
)

PROMOTION_STATUS_RESEARCH = "research"
ORDERS_ENABLED = False
SETUP_BUNDLE_DIR = "JackSparrow_SetupEffectiveness_BTCUSD"
SR_BUNDLE_DIR = "JackSparrow_SREffectiveness_BTCUSD"
HIGH_VOL_ATR_PCT = 0.02
TREND_ADX_MIN = 22.0
TREND_HURST_MIN = 0.52
LOW_VOL_ATR_PCT_MAX = 0.003
LOW_VOL_REGIME_MAX = 0.85
RANGE_ADX_MAX = 22.0
RANGE_VOL_REGIME_MAX = 1.05


def series_symbol(kind: str, symbol: str = SYMBOL) -> str:
    """Return the Delta symbol for an OHLCV or derivative candle series.

    Args:
        kind: ``ohlcv``, ``mark``, ``funding``, or ``oi``.
        symbol: Instrument symbol, default ``BTCUSD``.

    Returns:
        The public history symbol.

    Raises:
        ValueError: If ``kind`` is unknown.
    """
    if kind == "ohlcv":
        return symbol
    prefix = DERIVATIVE_PREFIX.get(kind)
    if prefix is None:
        raise ValueError(f"unknown series kind: {kind}")
    return f"{prefix}{symbol}"


def max_hold_bars(resolution: str) -> int:
    """Return the maximum holding window for one resolution.

    Args:
        resolution: One of ``RESOLUTIONS``.

    Returns:
        Bar count.

    Raises:
        ValueError: If the resolution is unknown.
    """
    if resolution not in MAX_HOLD_BARS:
        raise ValueError(f"unknown resolution: {resolution}")
    return int(MAX_HOLD_BARS[resolution])
