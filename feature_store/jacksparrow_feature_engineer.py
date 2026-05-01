"""Train/inference tabular parity: fit stores medians; transform applies same imputation."""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

import pandas as pd


class JackSparrowTrainMedianEngineer:
    """``fit`` / ``transform`` for labeled feature matrices (adaptive retrain / notebooks)."""

    def __init__(self, feature_cols: Optional[Iterable[str]] = None) -> None:
        self._cols: List[str] = list(feature_cols) if feature_cols else []
        self._medians: Optional[pd.Series] = None

    def fit(self, df: pd.DataFrame, feature_cols: Optional[Iterable[str]] = None) -> "JackSparrowTrainMedianEngineer":
        cols = list(feature_cols) if feature_cols is not None else self._cols
        if not cols:
            raise ValueError("feature_cols required")
        self._cols = cols
        self._medians = df[cols].median(numeric_only=True)
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if self._medians is None:
            raise RuntimeError("Call fit() before transform()")
        out = df[self._cols].copy()
        return out.fillna(self._medians)

    def transform_values(self, df: pd.DataFrame) -> Any:
        """Numpy matrix for sklearn / XGBoost."""
        return self.transform(df).values.astype("float64", copy=False)
