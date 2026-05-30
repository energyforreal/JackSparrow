"""Pickle compatibility for JackSparrow MSO v50 artifacts (Colab __main__ → agent)."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_labels import MSO_STATE_DIMENSIONS


class MarketStateBundleExport:
    """Serializable MSO bundle: horizon → state_dim → LightGBM classifier."""

    def __init__(
        self,
        horizon_models: Optional[Dict[str, Dict[str, Any]]] = None,
        feature_cols: Optional[List[str]] = None,
        state_dimensions: Optional[Tuple[str, ...]] = None,
        label_encoders: Optional[Dict[str, Dict[str, int]]] = None,
        class_orders: Optional[Dict[str, Tuple[str, ...]]] = None,
        training_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.horizon_models: Dict[str, Dict[str, Any]] = dict(horizon_models or {})
        self.feature_cols: List[str] = list(feature_cols or [])
        self.state_dimensions: Tuple[str, ...] = tuple(
            state_dimensions or MSO_STATE_DIMENSIONS
        )
        self.label_encoders: Dict[str, Dict[str, int]] = dict(label_encoders or {})
        self.class_orders: Dict[str, Tuple[str, ...]] = dict(class_orders or {})
        self.training_metadata: Dict[str, Any] = dict(training_metadata or {})

    def predict_horizon(
        self,
        horizon_key: str,
        X: np.ndarray,
        *,
        X_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Run all state heads for one horizon; return labels + probas."""
        models = self.horizon_models.get(horizon_key) or {}
        out: Dict[str, Any] = {}
        Xs = np.asarray(X, dtype=np.float64)
        if X_df is not None and len(X_df):
            Xs = X_df.values
        for dim in self.state_dimensions:
            model = models.get(dim)
            if model is None:
                continue
            proba = np.asarray(model.predict_proba(Xs), dtype=np.float64)
            classes = list(getattr(model, "classes_", []))
            idx = int(np.argmax(proba[0]))
            label = str(classes[idx]) if idx < len(classes) else str(idx)
            prob_map = {
                str(classes[i]): float(proba[0, i])
                for i in range(min(len(classes), proba.shape[1]))
            }
            out[dim] = label
            out[f"{dim}_proba"] = prob_map
        return out

    def predict_all_horizons(
        self,
        X: np.ndarray,
        *,
        X_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for hk in self.horizon_models:
            result[hk] = self.predict_horizon(hk, X, X_df=X_df)
        return result


# Colab unpickle: alias into __main__
def _register_pickle_aliases() -> None:
    main = sys.modules.get("__main__")
    if main is not None:
        setattr(main, "MarketStateBundleExport", MarketStateBundleExport)


_register_pickle_aliases()
