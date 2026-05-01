"""Warm-start incremental XGBoost retrain (native booster continuation)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd
import structlog
from sklearn.base import clone
from xgboost import XGBClassifier
import xgboost as xgb

logger = structlog.get_logger()


def _unwrap_classifier(pipeline_or_model: Any) -> XGBClassifier:
    """Return the underlying XGBClassifier from a dict pipeline or raw estimator."""
    if isinstance(pipeline_or_model, XGBClassifier):
        return pipeline_or_model
    if isinstance(pipeline_or_model, dict) and "model" in pipeline_or_model:
        inner = pipeline_or_model["model"]
    else:
        inner = pipeline_or_model
    if not isinstance(inner, XGBClassifier):
        raise TypeError(
            f"Adaptive retrain expects XGBClassifier, got {type(inner).__name__}"
        )
    return inner


def class_weights_to_sample_weight(
    y: np.ndarray,
    weights: Mapping[int, float],
) -> np.ndarray:
    """Map per-class weights to per-row sample weights."""
    out = np.ones(len(y), dtype=np.float64)
    for i, lab in enumerate(y):
        out[i] = float(weights.get(int(lab), 1.0))
    return out


def warm_start_retrain(
    old_pipeline_or_model: Any,
    X_train: np.ndarray,
    y_train: np.ndarray,
    sample_weight: np.ndarray,
    *,
    num_boost_round: int = 150,
) -> XGBClassifier:
    """Add trees on top of existing booster (Colab Cell 8 pattern).

    Args:
        old_pipeline_or_model: Dict with ``model`` key or an ``XGBClassifier``.
        X_train: Feature matrix (float).
        y_train: Integer labels 0/1/2.
        sample_weight: Per-row weights.
        num_boost_round: Additional boosting rounds.

    Returns:
        New ``XGBClassifier`` sharing params with the old model and updated booster.
    """
    old_clf = _unwrap_classifier(old_pipeline_or_model)
    old_booster = old_clf.get_booster()
    native_params = old_clf.get_xgb_params()
    native_params = dict(native_params)
    native_params["num_class"] = 3

    dtrain = xgb.DMatrix(
        X_train,
        label=y_train,
        weight=np.asarray(sample_weight, dtype=np.float64),
    )
    new_booster = xgb.train(
        native_params,
        dtrain,
        num_boost_round=int(num_boost_round),
        xgb_model=old_booster,
        verbose_eval=False,
    )
    new_model = clone(old_clf)
    new_model._Booster = new_booster
    # Clone does not copy fitted sklearn wrapper state; copy minimal attrs for predict.
    for attr in ("classes_", "_le", "n_features_in_", "_features_count"):
        if hasattr(old_clf, attr):
            try:
                setattr(new_model, attr, getattr(old_clf, attr))
            except Exception:
                pass
    if hasattr(new_model, "classes_") and not hasattr(new_model, "n_classes_"):
        new_model.n_classes_ = len(new_model.classes_)  # type: ignore[attr-defined]
    elif not hasattr(new_model, "n_classes_"):
        new_model.n_classes_ = int(native_params.get("num_class", 3))  # type: ignore[attr-defined]
    logger.info(
        "adaptive_warm_start_complete",
        service="agent",
        component="retrain_engine",
        num_boost_round=num_boost_round,
        n_samples=int(len(y_train)),
    )
    return new_model


def prepare_training_matrix(
    df: pd.DataFrame,
    feature_cols: list[str],
    *,
    ffill_limit: int = 5,
) -> tuple[pd.DataFrame, np.ndarray, pd.Series]:
    """Clean features + label like Colab adaptive cell (ffill only, no bfill)."""
    cols = feature_cols + ["label"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"prepare_training_matrix: missing columns {missing}")
    df_clean = df[cols].copy()
    df_clean[feature_cols] = (
        df_clean[feature_cols]
        .replace([np.inf, -np.inf], np.nan)
        .ffill(limit=ffill_limit)
    )
    df_clean = df_clean.dropna(subset=["label"])
    train_median = df_clean[feature_cols].median()
    X = df_clean[feature_cols].fillna(train_median).values.astype(np.float64)
    y = df_clean["label"].values.astype(np.int64, copy=False)
    return df_clean, X, train_median
