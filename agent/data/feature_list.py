"""
Canonical feature list for ML models.

Single source of truth for feature names used by training scripts and runtime
(agent feature requests, MCP orchestrator). Ensures training and inference
always use the same 50 features and prevents count/name drift.
"""

from typing import List

# 50 features: 16 price + 10 momentum + 8 trend + 8 volatility + 6 volume + 2 returns
FEATURE_LIST: List[str] = [
    # Price-based (16 features)
    'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
    'ema_12', 'ema_26', 'ema_50',
    'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
    'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
    # Momentum (10 features)
    'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
    'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
    'momentum_10', 'momentum_20',
    # Trend (8 features)
    'macd', 'macd_signal', 'macd_histogram',
    'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
    'trend_strength',
    # Volatility (8 features)
    'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
    'atr_14', 'atr_20',
    'volatility_10', 'volatility_20',
    # Volume (6 features)
    'volume_sma_20', 'volume_ratio', 'obv',
    'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
    # Returns (2 features)
    'returns_1h', 'returns_24h'
]

EXPECTED_FEATURE_COUNT: int = len(FEATURE_LIST)


def get_feature_list() -> List[str]:
    """Return the canonical feature list (copy to avoid mutation)."""
    return list(FEATURE_LIST)


def validate_feature_count(features: List[str]) -> bool:
    """Return True if feature count matches the canonical expected count."""
    return len(features) == EXPECTED_FEATURE_COUNT
