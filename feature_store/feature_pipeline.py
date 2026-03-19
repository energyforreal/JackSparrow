"""
Batch feature pipeline: identical logic for training and live inference.

Delegates to UnifiedFeatureEngine for single source of truth.
"""

from typing import Optional

import pandas as pd

from feature_store.feature_registry import FEATURE_LIST, EXPECTED_FEATURE_COUNT
from feature_store.unified_feature_engine import UnifiedFeatureEngine


def compute_features(
    df: pd.DataFrame,
    resolution_minutes: int = 15,
    fill_invalid: bool = True,
) -> pd.DataFrame:
    """
    Compute canonical 50 features from OHLCV DataFrame.
    Columns required: open, high, low, close, volume.
    Optional: timestamp (ignored).
    """
    engine = UnifiedFeatureEngine()
    return engine.compute_batch(
        df,
        resolution_minutes=resolution_minutes,
        fill_invalid=fill_invalid,
    )


class FeaturePipeline:
    """
    Pipeline that computes canonical features from OHLCV.
    Optionally validates output count/order.
    """

    def __init__(
        self,
        resolution_minutes: int = 15,
        fill_invalid: bool = True,
        validate: bool = True,
    ):
        self.resolution_minutes = resolution_minutes
        self.fill_invalid = fill_invalid
        self.validate = validate
        self._engine = UnifiedFeatureEngine()

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        feat = self._engine.compute_batch(
            df,
            resolution_minutes=self.resolution_minutes,
            fill_invalid=self.fill_invalid,
        )
        if self.validate:
            if list(feat.columns) != FEATURE_LIST:
                raise ValueError("Feature order mismatch")
            if len(feat.columns) != EXPECTED_FEATURE_COUNT:
                raise ValueError(
                    f"Feature count: expected {EXPECTED_FEATURE_COUNT}, "
                    f"got {len(feat.columns)}"
                )
        return feat

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.transform(df)
