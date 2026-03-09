"""
Canonical feature registry: single source of truth for feature names and order.

Training and inference must use this list and order. Schema is used for
feature_schema.json and drift validation.
"""

from typing import Any, Dict, List

# 50 features: 16 price + 10 momentum + 8 trend + 8 volatility + 6 volume + 2 returns
# Must match agent/data/feature_list.py for compatibility
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

FEATURE_VERSION = "1.0"


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
