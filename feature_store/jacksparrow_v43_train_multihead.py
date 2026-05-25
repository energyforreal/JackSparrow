"""Train and export JackSparrow v43 multi-head intraday bundle (2/6/12/24 bars)."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    V43_COMPATIBLE_FEATURE_VERSION,
)
from feature_store.jacksparrow_v43_horizon import build_execution_profile, forward_bars_to_minutes
from feature_store.jacksparrow_v43_multihead import (
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    V43_MULTIHEAD_ARTIFACT_FORMAT,
    V43_MULTIHEAD_MODEL_FAMILY,
    bars_to_horizon_key,
)

# Longer horizons: slightly relax cost mask (larger moves; avoid over-pruning 1h/2h).
V43_HORIZON_COST_SCALE: Dict[int, float] = {
    2: 1.0,
    6: 1.0,
    12: 0.85,
    24: 0.80,
}


def compute_v43_round_trip_cost_pct(
    *,
    maker_fee: float = 0.0005,
    slippage: float = 0.0003,
) -> float:
    """Price-return round-trip cost on the same scale as runtime Gate 5.

    Leverage affects position sizing elsewhere — it must not inflate label or
    meta-classifier cost masking (matches ``agent.core.v43_signal_gates``).
    """
    return 2.0 * (float(maker_fee) + float(slippage))


try:
    import lightgbm as lgb
    from lightgbm import LGBMClassifier
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import RobustScaler
    from xgboost import XGBRegressor
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "train multi-head requires lightgbm, xgboost, scikit-learn"
    ) from exc

from agent.models.v43_pickle_shims import EnsembleModel, LGBMModel, MultiHeadBundle


def build_forward_labels(close: pd.Series, forward_bars: int) -> pd.Series:
    c = close.astype(float)
    return c.shift(-int(forward_bars)) / c - 1.0


def build_cost_aware_forward_labels(
    close: pd.Series,
    forward_bars: int,
    *,
    round_trip_cost: float,
) -> Tuple[pd.Series, Dict[str, float]]:
    """Forward return labels; sub-cost moves become NaN (excluded from training)."""
    raw = build_forward_labels(close, forward_bars)
    cost = float(round_trip_cost)
    tradable = raw.abs() >= cost
    masked = raw.where(tradable, np.nan)
    valid = raw.notna()
    stats = {
        "round_trip_cost_pct": cost,
        "tradable_label_fraction": float(tradable[valid].mean()) if valid.any() else 0.0,
        "sub_cost_suppressed_fraction": float((valid & ~tradable).mean()) if valid.any() else 0.0,
    }
    return masked, stats


def _tradable_meta_labels(
    y: np.ndarray,
    round_trip_cost: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Binary meta target: 1 = net-long after costs, 0 = net-short after costs."""
    cost = float(round_trip_cost)
    tradable = (y > cost) | (y < -cost)
    y_meta = np.where(y > cost, 1, np.where(y < -cost, 0, -1)).astype(np.int8)
    return y_meta, tradable


def _fit_lgb_sklearn_compat(
    estimator: Any,
    X: np.ndarray,
    y: np.ndarray,
    *,
    eval_set: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None,
    eval_metric: Optional[str] = None,
    callbacks: Optional[List[Any]] = None,
) -> None:
    """Fit LightGBM sklearn estimators across sklearn/lightgbm version mismatches."""
    kwargs: Dict[str, Any] = {}
    if eval_set is not None:
        kwargs["eval_set"] = eval_set
    if eval_metric is not None:
        kwargs["eval_metric"] = eval_metric
    if callbacks is not None:
        kwargs["callbacks"] = callbacks
    try:
        estimator.fit(X, y, **kwargs)
        return
    except TypeError as exc:
        if "force_all_finite" not in str(exc):
            raise
    params = estimator.get_params()
    n_estimators = int(params.pop("n_estimators", 200))
    params.pop("n_jobs", None)
    params.pop("verbose", None)
    train_data = lgb.Dataset(X, label=y)
    valid_sets = [train_data]
    valid_names = ["train"]
    if eval_set:
        for i, (_xv, _yv) in enumerate(eval_set):
            valid_sets.append(lgb.Dataset(_xv, label=_yv))
            valid_names.append("valid" if i == 0 else f"valid{i}")
    booster = lgb.train(
        params,
        train_data,
        num_boost_round=n_estimators,
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )
    estimator._Booster = booster
    estimator.fitted_ = True


def _predict_lgb_proba_compat(estimator: Any, X: np.ndarray) -> np.ndarray:
    try:
        return estimator.predict_proba(X)
    except TypeError as exc:
        if "force_all_finite" not in str(exc):
            raise
    booster = getattr(estimator, "_Booster", None)
    if booster is None:
        raise RuntimeError("LightGBM estimator missing _Booster after compat fit")
    raw = booster.predict(X)
    p1 = np.asarray(raw, dtype=np.float64).ravel()
    p1 = np.clip(p1, 0.0, 1.0)
    return np.column_stack([1.0 - p1, p1])


def chronological_split_indices(
    n_rows: int,
    *,
    validation_fraction: float = 0.15,
    embargo_bars: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
    n = int(n_rows)
    val_size = max(1, int(n * validation_fraction))
    embargo = max(0, int(embargo_bars))
    val_start = max(0, n - val_size)
    train_end = max(0, val_start - embargo)
    train_idx = np.arange(0, train_end, dtype=np.int64)
    embargo_idx = np.arange(train_end, val_start, dtype=np.int64)
    val_idx = np.arange(val_start, n, dtype=np.int64)
    meta = {
        "split_method": "chronological_embargo",
        "validation_fraction": validation_fraction,
        "embargo_bars": embargo,
        "rows_total_after_dropna": n,
        "rows_train": int(len(train_idx)),
        "rows_embargo": int(len(embargo_idx)),
        "rows_validation": int(len(val_idx)),
    }
    return train_idx, embargo_idx, val_idx, meta


def _safe_corr(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if len(a) < 2 or np.nanstd(a) == 0 or np.nanstd(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _candidate_stats(
    mask: np.ndarray,
    gross_returns: np.ndarray,
    net_returns: np.ndarray,
    n_total: int,
) -> Dict[str, Any]:
    mask = np.asarray(mask, dtype=bool)
    gross = np.asarray(gross_returns, dtype=np.float64)[mask]
    net = np.asarray(net_returns, dtype=np.float64)[mask]
    if gross.size == 0:
        return {
            "count": 0,
            "coverage": 0.0,
            "gross_mean_return": None,
            "net_mean_return": None,
            "net_median_return": None,
            "hit_rate_gross_positive": None,
            "hit_rate_net_positive": None,
            "max_drawdown_proxy": 0.0,
        }
    peak = np.maximum.accumulate(np.cumsum(net))
    dd = float(np.min(net - peak)) if net.size else 0.0
    return {
        "count": int(gross.size),
        "coverage": float(gross.size / max(1, n_total)),
        "gross_mean_return": float(np.mean(gross)),
        "net_mean_return": float(np.mean(net)),
        "net_median_return": float(np.median(net)),
        "hit_rate_gross_positive": float(np.mean(gross > 0.0)),
        "hit_rate_net_positive": float(np.mean(net > 0.0)),
        "max_drawdown_proxy": dd,
    }


def _horizon_meta_classifier_params(forward_bars: int, rng: int) -> Dict[str, Any]:
    """Slightly richer meta models on longer horizons (more validation signal)."""
    fb = int(forward_bars)
    if fb >= 24:
        return {
            "n_estimators": 300,
            "num_leaves": 31,
            "min_child_samples": 80,
            "reg_lambda": 2.0,
            "reg_alpha": 0.1,
            "learning_rate": 0.04,
            "random_state": rng,
            "verbose": -1,
            "class_weight": "balanced",
        }
    if fb >= 12:
        return {
            "n_estimators": 250,
            "num_leaves": 23,
            "min_child_samples": 90,
            "reg_lambda": 2.0,
            "reg_alpha": 0.1,
            "learning_rate": 0.045,
            "random_state": rng,
            "verbose": -1,
            "class_weight": "balanced",
        }
    return {
        "n_estimators": 200,
        "num_leaves": 15,
        "min_child_samples": 100,
        "reg_lambda": 2.0,
        "reg_alpha": 0.1,
        "learning_rate": 0.05,
        "random_state": rng,
        "verbose": -1,
    }


def _validation_metrics_from_predictions(
    ensemble: EnsembleModel,
    lgbm_model: LGBMModel,
    *,
    val_pred: np.ndarray,
    y_va: np.ndarray,
    round_trip_cost: float,
    inference_path: str,
    label_mode: str,
    tradable_frac: float,
    threshold_source: str,
    meta_auc: Optional[float] = None,
) -> Dict[str, Any]:
    """Shared thresholding + validation metrics for meta or regressor-mean stacks."""
    dt_long = max(float(np.nanpercentile(val_pred, 75)), 1e-6)
    dt_short = min(float(np.nanpercentile(val_pred, 25)), -1e-6)
    dt_short_mag = abs(dt_short)
    ensemble.threshold = dt_long
    ensemble.dynamic_threshold = dt_long
    ensemble.short_threshold = dt_short_mag
    lgbm_model.dynamic_threshold = dt_long
    lgbm_model.short_threshold = dt_short_mag
    lgbm_model.regime_thresholds = {
        "neutral": dt_long,
        "ranging": dt_long,
        "trending": dt_long,
        "crisis": dt_long,
    }

    directional_mask = y_va != 0
    long_cand = val_pred > dt_long
    short_cand = val_pred < dt_short
    long_net = y_va - round_trip_cost
    short_gross = -y_va
    short_net = short_gross - round_trip_cost

    vm: Dict[str, Any] = {
        "model_family": "jacksparrow_v43_regression",
        "target": "cost_aware_forward_return",
        "label_mode": label_mode,
        "round_trip_cost_pct": float(round_trip_cost),
        "tradable_label_fraction": tradable_frac,
        "inference_path": inference_path,
        "threshold_source": threshold_source,
        "threshold_percentile": 75.0,
        "short_threshold_percentile": 25.0,
        "dynamic_threshold": dt_long,
        "short_threshold": dt_short_mag,
        "validation_rmse": float(np.sqrt(np.mean((val_pred - y_va) ** 2))),
        "validation_mae": float(np.mean(np.abs(val_pred - y_va))),
        "validation_corr": _safe_corr(val_pred, y_va),
        "directional_accuracy": float(
            np.mean(np.sign(val_pred[directional_mask]) == np.sign(y_va[directional_mask]))
        )
        if np.any(directional_mask)
        else None,
        "prediction_mean": float(np.mean(val_pred)),
        "prediction_std": float(np.std(val_pred)),
        "target_mean": float(np.mean(y_va)),
        "target_std": float(np.std(y_va)),
        "long_candidates": _candidate_stats(long_cand, y_va, long_net, len(y_va)),
        "short_candidates": _candidate_stats(short_cand, short_gross, short_net, len(y_va)),
    }
    if meta_auc is not None:
        vm["meta_auc"] = meta_auc
    return vm


def train_horizon_ensemble(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    rng: int = 42,
    round_trip_cost: float = 0.0016,
    forward_bars: int = 6,
    use_meta_stack: bool = True,
) -> Tuple[EnsembleModel, Dict[str, Any]]:
    """Train one horizon ensemble (LGBM + XGB + RF); optional meta-classifier stack."""
    feat_cols = list(X_train.columns)
    y_tr = y_train.values.astype(np.float64)
    y_va = y_val.values.astype(np.float64)

    lgbm_model = LGBMModel()
    lgbm_model.scaler = RobustScaler()
    X_train_lgb = lgbm_model.scaler.fit_transform(X_train.values)
    X_val_lgb = lgbm_model.scaler.transform(X_val.values)

    lgb_inner = lgb.LGBMRegressor(
        n_estimators=400,
        learning_rate=0.05,
        num_leaves=63,
        max_depth=8,
        min_child_samples=100,
        reg_lambda=1.0,
        reg_alpha=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=rng,
        verbose=-1,
    )
    _fit_lgb_sklearn_compat(
        lgb_inner,
        X_train_lgb,
        y_tr,
        eval_set=[(X_val_lgb, y_va)],
        eval_metric="l2",
    )
    lgbm_model.lgbm = lgb_inner
    lgbm_model.feature_cols = feat_cols

    ensemble = EnsembleModel()
    ensemble._ens_scaler = RobustScaler()
    X_train_s = ensemble._ens_scaler.fit_transform(X_train.values)
    X_val_s = ensemble._ens_scaler.transform(X_val.values)

    xgb = XGBRegressor(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        min_child_weight=10,
        reg_lambda=1.0,
        reg_alpha=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=rng,
        n_jobs=-1,
        verbosity=0,
        early_stopping_rounds=30,
    )
    try:
        xgb.fit(X_train_s, y_tr, eval_set=[(X_val_s, y_va)], verbose=False)
    except TypeError:
        xgb.fit(X_train_s, y_tr)

    rf = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_leaf=100,
        max_features=0.5,
        random_state=rng,
        n_jobs=-1,
    )
    rf.fit(X_train_s, y_tr)

    ensemble.lgbm_model = lgbm_model
    ensemble.xgb = xgb
    ensemble.rf = rf
    ensemble.feature_cols = feat_cols
    ensemble._is_fitted = True

    _, trad_va = _tradable_meta_labels(y_va, round_trip_cost)
    tradable_frac = float(np.mean(trad_va)) if trad_va.size else 0.0

    if not use_meta_stack:
        ensemble.meta = None
        ensemble.calibrator = None
        val_pred = np.asarray(
            ensemble.predict(
                X_val.values,
                X_df=X_val,
                inference_stack="regressor_mean",
            ),
            dtype=np.float64,
        ).ravel()
        validation_metrics = _validation_metrics_from_predictions(
            ensemble,
            lgbm_model,
            val_pred=val_pred,
            y_va=y_va,
            round_trip_cost=round_trip_cost,
            inference_path="regressor_mean",
            label_mode="regressor_mean_stack",
            tradable_frac=tradable_frac,
            threshold_source="validation_regressor_mean_percentile",
        )
        return ensemble, validation_metrics

    X_stack_train = ensemble._base_predictions(X_train.values)
    X_stack_val = ensemble._base_predictions(X_val.values)
    y_meta_tr, trad_tr = _tradable_meta_labels(y_tr, round_trip_cost)
    y_meta_va, trad_va = _tradable_meta_labels(y_va, round_trip_cost)
    label_mode = "cost_aware_tradable"
    use_tr = trad_tr & (y_meta_tr >= 0)
    use_va = trad_va & (y_meta_va >= 0)
    if int(use_tr.sum()) < 80 or int(use_va.sum()) < 30:
        label_mode = "gross_direction_fallback"
        y_bin_train = (y_tr > 0).astype(int)
        y_bin_val = (y_va > 0).astype(int)
        X_meta_tr, y_meta_fit_tr = X_stack_train, y_bin_train
        X_meta_va, y_meta_fit_va = X_stack_val, y_bin_val
        auc_mask = np.ones(len(y_va), dtype=bool)
    else:
        y_bin_train = y_meta_tr[use_tr].astype(int)
        y_bin_val = y_meta_va[use_va].astype(int)
        X_meta_tr = X_stack_train[use_tr]
        X_meta_va = X_stack_val[use_va]
        y_meta_fit_tr = y_bin_train
        y_meta_fit_va = y_bin_val
        auc_mask = use_va

    meta_clf = LGBMClassifier(**_horizon_meta_classifier_params(forward_bars, rng))
    _fit_lgb_sklearn_compat(
        meta_clf,
        X_meta_tr,
        y_meta_fit_tr,
        eval_set=[(X_meta_va, y_meta_fit_va)],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )
    meta_val_proba = np.full(len(y_va), 0.5, dtype=np.float64)
    if int(auc_mask.sum()) > 0:
        meta_val_proba[auc_mask] = _predict_lgb_proba_compat(
            meta_clf, X_stack_val[auc_mask]
        )[:, 1]
    calibrator = Ridge(alpha=1.0)
    calibrator.fit(meta_val_proba.reshape(-1, 1), y_va)

    ensemble.meta = meta_clf
    ensemble.calibrator = calibrator

    val_pred = np.asarray(
        ensemble.predict(X_val.values, X_df=X_val), dtype=np.float64
    ).ravel()

    try:
        from sklearn.metrics import roc_auc_score

        if label_mode == "cost_aware_tradable" and int(auc_mask.sum()) > 10:
            meta_auc = float(roc_auc_score(y_meta_va[auc_mask], meta_val_proba[auc_mask]))
        else:
            meta_auc = float(roc_auc_score((y_va > 0).astype(int), meta_val_proba))
    except Exception:
        meta_auc = 0.5

    validation_metrics = _validation_metrics_from_predictions(
        ensemble,
        lgbm_model,
        val_pred=val_pred,
        y_va=y_va,
        round_trip_cost=round_trip_cost,
        inference_path="meta_calibrator",
        label_mode=label_mode,
        tradable_frac=tradable_frac,
        threshold_source="validation_meta_prediction_percentile",
        meta_auc=meta_auc,
    )

    return ensemble, validation_metrics


def train_multihead_from_feature_matrix(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    feat_cols: Optional[List[str]] = None,
    validation_fraction: float = 0.15,
    rng: int = 42,
    maker_fee: float = 0.0005,
    slippage: float = 0.0003,
    leverage: int = 3,
    cost_aware_labels: bool = True,
    use_meta_stack: bool = True,
) -> Tuple[MultiHeadBundle, Dict[str, Any]]:
    """Train all horizon heads on shared features.

    When ``use_meta_stack`` is False, each head uses the mean of base regressors only
    (``inference_path=regressor_mean``) with no LGBMClassifier meta-learner or Ridge calibrator.
    """
    cols = feat_cols or list(V43_CANONICAL_FEATURES)
    missing = [c for c in cols if c not in df_feat.columns]
    if missing:
        raise ValueError(f"feature matrix missing columns: {missing[:8]}")

    round_trip_cost = compute_v43_round_trip_cost_pct(
        maker_fee=maker_fee,
        slippage=slippage,
    )
    bundle = MultiHeadBundle()
    horizons_meta: Dict[str, Any] = {}
    split_meta_global: Dict[str, Any] = {}

    for hkey in V43_HORIZON_KEYS:
        fb = int(V43_HORIZON_KEY_TO_BARS[hkey])
        label_mode_horizon = "cost_aware" if cost_aware_labels else "gross_forward_return"
        cost_scale = float(V43_HORIZON_COST_SCALE.get(fb, 1.0))
        effective_cost = round_trip_cost * cost_scale
        if cost_aware_labels:
            y_raw, label_stats = build_cost_aware_forward_labels(
                close, fb, round_trip_cost=effective_cost
            )
            label_stats["horizon_cost_scale"] = cost_scale
            label_stats["effective_round_trip_cost_pct"] = effective_cost
        else:
            y_raw = build_forward_labels(close, fb)
            label_stats = {"tradable_label_fraction": 1.0, "sub_cost_suppressed_fraction": 0.0}
        work = df_feat[cols].copy()
        work["target"] = y_raw.values
        work = work.replace([np.inf, -np.inf], np.nan).dropna()
        if len(work) < 500 and cost_aware_labels:
            y_gross = build_forward_labels(close, fb)
            work = df_feat[cols].copy()
            work["target"] = y_gross.values
            work = work.replace([np.inf, -np.inf], np.nan).dropna()
            label_mode_horizon = "gross_forward_return_fallback"
            label_stats = {
                **label_stats,
                "cost_aware_fallback": True,
                "fallback_reason": "insufficient_tradable_rows",
            }
        if len(work) < 500:
            raise ValueError(f"insufficient rows for horizon {hkey}: {len(work)}")

        train_idx, embargo_idx, val_idx, split_meta = chronological_split_indices(
            len(work),
            validation_fraction=validation_fraction,
            embargo_bars=fb,
        )
        split_meta_global[hkey] = split_meta

        X = work[cols]
        y = work["target"]
        X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
        X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]

        ensemble, vm = train_horizon_ensemble(
            X_train,
            y_train,
            X_val,
            y_val,
            rng=rng + fb,
            round_trip_cost=round_trip_cost,
            forward_bars=fb,
            use_meta_stack=use_meta_stack,
        )
        bundle.set_head(fb, ensemble)

        horizons_meta[hkey] = {
            "forward_bars": fb,
            "horizon_minutes": forward_bars_to_minutes(fb),
            "horizon_key": hkey,
            "validation_metrics": vm,
            "dynamic_threshold": vm.get("dynamic_threshold"),
            "short_threshold": vm.get("short_threshold"),
            "split": split_meta,
            "execution_profile": build_execution_profile(fb),
            "label_stats": label_stats,
            "label_mode": label_mode_horizon,
        }

    exported_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "version": "v43",
        "model_family": V43_MULTIHEAD_MODEL_FAMILY,
        "artifact_format": V43_MULTIHEAD_ARTIFACT_FORMAT,
        "compatible_feature_version": V43_COMPATIBLE_FEATURE_VERSION,
        "feature_count": len(cols),
        "features": list(cols),
        "target_definition": (
            "cost_aware_forward_return" if cost_aware_labels else "simple_forward_return"
        ),
        "primary_execution_horizon_bars": 6,
        "horizons": horizons_meta,
        "split": split_meta_global,
        "exported_at": exported_at,
        "runtime_cost_assumptions": {
            "maker_fee_rate": maker_fee,
            "slippage_pct": slippage,
            "leverage_assumption": leverage,
            "round_trip_cost_pct": round_trip_cost,
            "round_trip_cost_includes_leverage": False,
        },
    }
    return bundle, metadata


def artifact_dict_from_bundle(
    bundle: MultiHeadBundle,
    feature_engineer: Any,
    *,
    features: Optional[List[str]] = None,
) -> Dict[str, Any]:
    feats = features or list(V43_CANONICAL_FEATURES)
    return {
        "format": V43_MULTIHEAD_ARTIFACT_FORMAT,
        "model": bundle,
        "feature_engineer": feature_engineer,
        "features": feats,
    }
