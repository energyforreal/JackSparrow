"""
Live feature cache: rolling window of candles for incremental feature computation.

The agent maintains this cache and passes the window to FeaturePipeline
so live inference uses the same feature logic as training.
"""

from collections import deque
from typing import Any, Dict, List, Optional

import pandas as pd

from feature_store.feature_pipeline import FeaturePipeline, compute_features
from feature_store.feature_registry import FEATURE_LIST, EXPECTED_FEATURE_COUNT


class FeatureCache:
    """
    Rolling window of OHLCV candles. Call update(candle) on each new candle,
    then dataframe() to get the window and compute_features() for the last row.
    """

    def __init__(
        self,
        maxlen: int = 500,
        resolution_minutes: int = 15,
    ):
        self._maxlen = maxlen
        self._resolution_minutes = resolution_minutes
        self._deque: deque = deque(maxlen=maxlen)
        self._pipeline = FeaturePipeline(
            resolution_minutes=resolution_minutes,
            fill_invalid=True,
            validate=True,
        )

    def update(self, candle: Dict[str, Any]) -> None:
        """Append one candle. Expect keys: open, high, low, close, volume; optional timestamp."""
        self._deque.append(dict(candle))

    def extend(self, candles: List[Dict[str, Any]]) -> None:
        """Append multiple candles."""
        for c in candles:
            self.update(c)

    def dataframe(self) -> pd.DataFrame:
        """Return current window as DataFrame with columns open, high, low, close, volume."""
        if not self._deque:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return pd.DataFrame(list(self._deque))

    def get_latest_features(self) -> Optional[pd.DataFrame]:
        """
        Compute features for the full window and return the last row as (1, 50) DataFrame.
        Returns None if window has too few rows for feature computation.
        """
        df = self.dataframe()
        if df.empty or len(df) < 30:
            return None
        feat = self._pipeline.transform(df)
        return feat.iloc[[-1]]

    def get_latest_feature_vector(self) -> Optional[List[float]]:
        """Return the last row of features as a list of 50 floats, or None."""
        latest = self.get_latest_features()
        if latest is None or latest.empty:
            return None
        return latest.iloc[0].tolist()

    @property
    def expected_feature_count(self) -> int:
        return EXPECTED_FEATURE_COUNT

    @property
    def feature_names(self) -> List[str]:
        return list(FEATURE_LIST)

    def __len__(self) -> int:
        return len(self._deque)
