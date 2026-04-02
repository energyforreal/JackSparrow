"""
Canonical feature registry: single source of truth for feature names and order.

Training and inference must use this list and order. Schema is used for
feature_schema.json and drift validation.
"""

from typing import Any, Dict, List

# 50 features: 16 price + 10 momentum + 8 trend + 8 volatility + 6 volume + 2 returns
# Canonical source used by both runtime and training paths.
FEATURE_LIST: List[str] = [
    # Price-based (16)
    "sma_10", "sma_20", "sma_50", "sma_100", "sma_200",
    "ema_12", "ema_26", "ema_50",
    "close_sma_20_ratio", "close_sma_50_ratio", "close_sma_200_ratio",
    "high_low_spread", "close_open_ratio", "body_size", "upper_shadow", "lower_shadow",
    # Momentum (10)
    "rsi_14", "rsi_7", "stochastic_k_14", "stochastic_d_14",
    "williams_r_14", "cci_20", "roc_10", "roc_20",
    "momentum_10", "momentum_20",
    # Trend (8)
    "macd", "macd_signal", "macd_histogram",
    "adx_14", "aroon_up", "aroon_down", "aroon_oscillator",
    "trend_strength",
    # Volatility (8)
    "bb_upper", "bb_lower", "bb_width", "bb_position",
    "atr_14", "atr_20",
    "volatility_10", "volatility_20",
    # Volume (6)
    "volume_sma_20", "volume_ratio", "obv",
    "volume_price_trend", "accumulation_distribution", "chaikin_oscillator",
    # Returns (2)
    "returns_1h", "returns_24h",
]

EXPECTED_FEATURE_COUNT: int = len(FEATURE_LIST)

# Candlestick pattern features (~40)
CANDLESTICK_FEATURES: List[str] = [
    "cdl_doji", "cdl_long_legged_doji", "cdl_dragonfly_doji", "cdl_gravestone_doji",
    "cdl_hammer", "cdl_inv_hammer", "cdl_hanging_man", "cdl_shooting_star",
    "cdl_bull_marubozu", "cdl_bear_marubozu", "cdl_spinning_top",
    "cdl_bull_engulfing", "cdl_bear_engulfing", "cdl_bull_harami", "cdl_bear_harami",
    "cdl_piercing", "cdl_dark_cloud", "cdl_tweezer_top", "cdl_tweezer_bottom",
    "cdl_bull_kicker", "cdl_bear_kicker",
    "cdl_morning_star", "cdl_evening_star", "cdl_three_white_soldiers",
    "cdl_three_black_crows", "cdl_three_inside_up", "cdl_three_inside_down",
    "cdl_abandoned_baby_bull", "cdl_abandoned_baby_bear",
    "cdl_bull_score", "cdl_bear_score", "cdl_net_score", "cdl_reversal_signal",
    "cdl_indecision_score", "cdl_body_ratio", "cdl_upper_wick_ratio",
    "cdl_lower_wick_ratio", "cdl_consecutive_bull", "cdl_consecutive_bear",
]

# Chart pattern features (~32)
CHART_PATTERN_FEATURES: List[str] = [
    "sr_support_dist_pct", "sr_resistance_dist_pct",
    "sr_at_support", "sr_at_resistance",
    "sr_support_strength", "sr_resistance_strength", "sr_range_position",
    "tl_uptrend_detected", "tl_downtrend_detected", "tl_trend_slope",
    "tl_dist_to_trendline", "tl_near_trendline", "tl_breakout_up", "tl_breakout_down",
    "chp_bull_flag", "chp_bear_flag", "chp_bull_flag_strength", "chp_bear_flag_strength",
    "chp_asc_triangle", "chp_desc_triangle", "chp_sym_triangle", "chp_triangle_apex_dist",
    "chp_double_top", "chp_double_bottom", "chp_double_top_dist", "chp_double_bottom_dist",
    "chp_hs_detected", "chp_ihs_detected",
    "bo_at_high", "bo_at_low", "bo_volume_confirmation", "bo_breakout_score",
]

# Multi-timeframe context (derived from primary OHLCV via resample; 5m primary in production).
# Appended after patterns for backward-compatible ordering of base blocks.
MTF_CONTEXT_FEATURES: List[str] = [
    "mtf_15m_rsi_14",
    "mtf_15m_ema_12",
    "mtf_3m_rsi_14",
    "mtf_3m_ema_12",
    "mtf_1m_vol_ratio",
]

# Regime-awareness features produced by notebook/live feature layer.
REGIME_FEATURES: List[str] = [
    "regime_state",
    "regime_is_ranging",
    "regime_is_trending",
    "regime_is_volatile",
]

# Expanded: canonical + candlestick + chart patterns + MTF context + regime flags.
EXPANDED_FEATURE_LIST: List[str] = (
    FEATURE_LIST
    + CANDLESTICK_FEATURES
    + CHART_PATTERN_FEATURES
    + MTF_CONTEXT_FEATURES
    + REGIME_FEATURES
)

FEATURE_VERSION = "1.2"


def get_feature_list() -> List[str]:
    """Return the canonical feature list (copy)."""
    return list(FEATURE_LIST)


def validate_feature_count(features: List[str]) -> bool:
    """Return True if feature count matches canonical."""
    return len(features) == EXPECTED_FEATURE_COUNT


def validate_feature_order(feature_names: List[str]) -> bool:
    """Return True if names match canonical order."""
    if len(feature_names) != EXPECTED_FEATURE_COUNT:
        return False
    return all(a == b for a, b in zip(FEATURE_LIST, feature_names))


def get_feature_schema(
    include_stats: bool = False,
    training_stats: Dict[str, Dict[str, float]] | None = None,
) -> Dict[str, Any]:
    """
    Return schema dict for feature_schema.json.
    If include_stats and training_stats are provided, add mean/std for drift baseline.
    """
    schema: Dict[str, Any] = {
        "version": FEATURE_VERSION,
        "feature_count": EXPECTED_FEATURE_COUNT,
        "features": FEATURE_LIST,
    }
    if include_stats and training_stats:
        schema["training_stats"] = training_stats
    return schema
