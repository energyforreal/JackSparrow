"""Pickle compatibility for JackSparrow MSO v50 artifacts (Colab __main__ → agent)."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from feature_store.jacksparrow_mso_labels import MSO_STATE_DIMENSIONS

# Default trend feature exclusions (must match training notebook MSO_TREND_EXCLUDED_FEATURES).
_DEFAULT_TREND_EXCLUDED: Tuple[str, ...] = ("adx_14", "trend_mom", "hurst_60")


def _unwrap_estimator(model: Any) -> Any:
    """Return inner fitted estimator when wrapped by CalibratedClassifierCV."""
    calibrated = getattr(model, "calibrated_classifiers_", None)
    if calibrated:
        try:
            return calibrated[0].estimator
        except (IndexError, AttributeError, TypeError):
            pass
    base = getattr(model, "base_estimator", None)
    if base is not None:
        return base
    estimator = getattr(model, "estimator", None)
    if estimator is not None:
        return estimator
    return model


def _decode_class_code(code: int, class_order: Tuple[str, ...], model: Any) -> str:
    """Map LightGBM integer prediction to canonical string label."""
    order = list(class_order)
    lgb_classes = list(getattr(_unwrap_estimator(model), "classes_", []))
    c = int(code)
    if lgb_classes and c >= len(order) and c < len(lgb_classes):
        c = int(lgb_classes[c])
    if 0 <= c < len(order):
        return str(order[c])
    if str(c) in order:
        return str(c)
    return str(c)


def _proba_to_label_map(
    proba_row: np.ndarray,
    class_order: Tuple[str, ...],
    model: Any,
) -> Dict[str, float]:
    """Build string-keyed probability map aligned with class_order."""
    order = list(class_order)
    proba_row = np.asarray(proba_row, dtype=np.float64).ravel()
    prob_map: Dict[str, float] = {str(c): 0.0 for c in order}
    for col_idx in range(min(len(proba_row), len(order))):
        prob_map[str(order[col_idx])] = float(proba_row[col_idx])
    return prob_map


class MarketStateBundleExport:
    """Serializable MSO bundle: horizon → state_dim → LightGBM classifier."""

    def __init__(
        self,
        horizon_models: Optional[Dict[str, Dict[str, Any]]] = None,
        feature_cols: Optional[List[str]] = None,
        state_dimensions: Optional[Tuple[str, ...]] = None,
        label_encoders: Optional[Dict[str, Dict[str, int]]] = None,
        class_orders: Optional[Dict[str, Tuple[str, ...]]] = None,
        head_feature_cols: Optional[Dict[str, List[str]]] = None,
        training_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.horizon_models: Dict[str, Dict[str, Any]] = dict(horizon_models or {})
        self.feature_cols: List[str] = list(feature_cols or [])
        self.state_dimensions: Tuple[str, ...] = tuple(
            state_dimensions or MSO_STATE_DIMENSIONS
        )
        self.label_encoders: Dict[str, Dict[str, int]] = dict(label_encoders or {})
        self.class_orders: Dict[str, Tuple[str, ...]] = dict(class_orders or {})
        self.head_feature_cols: Dict[str, List[str]] = dict(head_feature_cols or {})
        self.training_metadata: Dict[str, Any] = dict(training_metadata or {})

    def _resolve_head_columns(
        self,
        head_key: str,
        dim: str,
        model: Any,
    ) -> List[str]:
        stored = self.head_feature_cols.get(head_key)
        if stored:
            return list(stored)
        full = list(self.feature_cols)
        est = _unwrap_estimator(model)
        n_feat = getattr(est, "n_features_in_", None)
        if n_feat is None:
            n_feat = getattr(est, "n_features_", None)
        if n_feat is None or n_feat == len(full):
            return full
        if dim == "trend_regime":
            cand = [c for c in full if c not in _DEFAULT_TREND_EXCLUDED]
            if len(cand) == int(n_feat):
                return cand
        raise ValueError(
            f"MSO head {head_key}: model expects {n_feat} features but bundle has "
            f"{len(full)} and head_feature_cols is missing — re-run training or "
            f"reload a bundle exported after per-head feature tracking was added."
        )

    def _feature_matrix_for_head(
        self,
        horizon_key: str,
        dim: str,
        X: np.ndarray,
        model: Any,
        *,
        X_df: Optional[pd.DataFrame] = None,
    ) -> np.ndarray:
        head_key = f"{horizon_key}:{dim}"
        head_cols = self._resolve_head_columns(head_key, dim, model)
        if X_df is not None and len(X_df):
            missing = [c for c in head_cols if c not in X_df.columns]
            if missing:
                raise ValueError(
                    f"MSO head {head_key} missing features: {missing[:8]}"
                )
            return X_df.loc[:, head_cols].to_numpy(dtype=np.float64)
        Xs = np.asarray(X, dtype=np.float64)
        if Xs.ndim == 1:
            Xs = Xs.reshape(1, -1)
        if len(head_cols) == Xs.shape[1]:
            return Xs
        if self.feature_cols and Xs.shape[1] == len(self.feature_cols):
            idx = [self.feature_cols.index(c) for c in head_cols]
            return Xs[:, idx]
        raise ValueError(
            f"MSO head {head_key}: expected {len(head_cols)} features, got {Xs.shape[1]}"
        )

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
        for dim in self.state_dimensions:
            model = models.get(dim)
            if model is None:
                continue
            Xs = self._feature_matrix_for_head(horizon_key, dim, X, model, X_df=X_df)
            proba = np.asarray(model.predict_proba(Xs), dtype=np.float64)
            class_order = self.class_orders.get(f"{horizon_key}:{dim}")
            if not class_order:
                class_order = tuple(
                    str(c)
                    for c in getattr(_unwrap_estimator(model), "classes_", [])
                )
            proba_row = proba[0] if proba.ndim > 1 else proba
            pred_codes = model.predict(Xs)
            code = int(np.atleast_1d(pred_codes)[0])
            label = _decode_class_code(code, tuple(class_order), model)
            prob_map = _proba_to_label_map(proba_row, tuple(class_order), model)
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
