"""
Canonical feature list for ML models.

Re-exports from feature_store.feature_registry (single source of truth).
Ensures training and inference always use the same 50 features.
"""

from feature_store.feature_registry import (
    EXPECTED_FEATURE_COUNT,
    FEATURE_LIST,
    get_feature_list,
    validate_feature_count,
)

__all__ = [
    "FEATURE_LIST",
    "EXPECTED_FEATURE_COUNT",
    "get_feature_list",
    "validate_feature_count",
]
