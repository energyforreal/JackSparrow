"""
Feature store: canonical feature list, batch pipeline, and live cache.

Training and inference use the same feature logic via:
- feature_registry: canonical feature names and schema
- feature_pipeline: compute features from OHLCV DataFrame (batch)
- feature_cache: rolling candle window for live incremental features
"""

from feature_store.feature_registry import (
    FEATURE_LIST,
    EXPECTED_FEATURE_COUNT,
    get_feature_list,
    get_feature_schema,
    validate_feature_count,
    validate_feature_order,
)
from feature_store.feature_pipeline import FeaturePipeline, compute_features
from feature_store.feature_cache import FeatureCache
from feature_store.drift import (
    load_training_stats,
    check_drift,
    drift_checker_from_schema,
)

__all__ = [
    "FEATURE_LIST",
    "EXPECTED_FEATURE_COUNT",
    "get_feature_list",
    "get_feature_schema",
    "validate_feature_count",
    "validate_feature_order",
    "FeaturePipeline",
    "compute_features",
    "FeatureCache",
    "load_training_stats",
    "check_drift",
    "drift_checker_from_schema",
]
