"""Train and export JackSparrow v43 multi-head intraday bundle (2/6/12/24 bars)."""

from __future__ import annotations

import json
import os
import warnings
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    V43_COMPATIBLE_FEATURE_VERSION,
)
from feature_store.jacksparrow_v43_horizon import (
    V43_FORWARD_TARGET_BARS_DEFAULT,
    build_execution_profile,
    forward_bars_to_minutes,
)
from feature_store.jacksparrow_v43_multihead import (
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    V43_MULTIHEAD_ARTIFACT_FORMAT,
    V43_MULTIHEAD_MODEL_FAMILY,
    bars_to_horizon_key,
)

# Longer horizons: slightly relax cost mask (larger moves; avoid over-pruning 1h/2h).
V43_HORIZON_COST_SCALE: Dict[int, float] = {
    2: 0.3,
    6: 1.0,
    12: 0.7,
    24: 0.5,
}

# OI model features vs microstructure (ticker-only; often zero without CSV).
V43_OI_FEATURE_COLS: Tuple[str, ...] = (
    "oi_zscore",
    "oi_change_6",
    "oi_price_divergence",
    "oi_acceleration",
    "oi_delta_z",
)
V43_MICROSTRUCTURE_FEATURE_COLS: Tuple[str, ...] = (
    "bid_ask_imbalance",
    "spread_bps",
    "funding_x_oi",
    "funding_predicted_zscore",
)
V43_DERIVATIVES_SPARSE_FEATURE_COLS: Tuple[str, ...] = (
    V43_OI_FEATURE_COLS + V43_MICROSTRUCTURE_FEATURE_COLS
)


def compute_v43_round_trip_cost_pct(
    *,
    maker_fee: float = 0.0002,
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

from agent.models.v43_pickle_shims import (
    EnsembleModel,
    LGBMModel,
    MultiHeadBundle,
    StateHeadModel,
)
from feature_store.jacksparrow_v43_labels import (
    V43_REGIME_CLASSES,
    V43_HORIZON_FEATURE_MASKS,
    V43_STATE_HEAD_FEATURE_TIERS,
    build_cost_aware_forward_labels,
    build_forward_labels,
    build_regime_labels,
    build_trade_quality_labels,
    build_vol_expansion_labels,
)

# Re-export label helpers for notebooks/tests that import from this module.
__all__ = [
    "build_forward_labels",
    "build_cost_aware_forward_labels",
    "train_multihead_from_feature_matrix",
    "train_state_heads_from_feature_matrix",
]


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


def resolve_min_dynamic_threshold(round_trip_cost: float) -> float:
    """Floor long/short thresholds at a fraction of round-trip cost (default 50%)."""
    frac_raw = os.environ.get("V43_MIN_THRESHOLD_COST_FRACTION", "0.5").strip()
    try:
        frac = float(frac_raw)
    except ValueError:
        frac = 1.0
    return float(round_trip_cost) * max(0.0, frac)


def resolve_validation_threshold_percentiles() -> tuple[float, float]:
    """Long/short validation percentiles for dynamic thresholds (env-tunable).

    Defaults: 90 / 10 (~10–15% candidate coverage vs legacy 75/25).
    """
    legacy = os.environ.get("V43_THRESHOLD_PERCENTILE", "").strip()
    long_raw = os.environ.get("V43_THRESHOLD_PERCENTILE_LONG", legacy or "90").strip()
    short_raw = os.environ.get("V43_THRESHOLD_PERCENTILE_SHORT", "").strip()
    long_p = float(long_raw or "90")
    if short_raw:
        short_p = float(short_raw)
    elif legacy:
        short_p = 100.0 - long_p
    else:
        short_p = 10.0
    long_p = float(min(99.0, max(50.0, long_p)))
    short_p = float(min(50.0, max(1.0, short_p)))
    if long_p <= short_p:
        short_p = max(1.0, long_p - 10.0)
    return long_p, short_p


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


def _feature_column_std(df_feat: pd.DataFrame, col: str) -> float:
    if col not in df_feat.columns:
        return 0.0
    s = pd.to_numeric(df_feat[col], errors="coerce").fillna(0.0)
    return float(s.std())


def _audit_sparse_derivatives_features(
    df_feat: pd.DataFrame,
    feat_cols: List[str],
    *,
    oi_std_threshold: float = 1e-8,
) -> Tuple[List[str], Dict[str, Any]]:
    """Warn when OI features have no variance or microstructure is all zeros."""
    oi_cols = [c for c in V43_OI_FEATURE_COLS if c in feat_cols]
    micro_cols = [c for c in V43_MICROSTRUCTURE_FEATURE_COLS if c in feat_cols]
    audit: Dict[str, Any] = {
        "oi_feature_columns": oi_cols,
        "microstructure_columns": micro_cols,
        "oi_feature_std": {},
        "microstructure_zero_fraction": {},
    }

    oi_stds: Dict[str, float] = {}
    for col in oi_cols:
        oi_stds[col] = _feature_column_std(df_feat, col)
    audit["oi_feature_std"] = oi_stds
    max_oi_std = max(oi_stds.values()) if oi_stds else 0.0
    audit["oi_feature_std_max"] = max_oi_std

    micro_zero: Dict[str, float] = {}
    for col in micro_cols:
        series = pd.to_numeric(df_feat[col], errors="coerce").fillna(0.0)
        micro_zero[col] = float((series.abs() < 1e-12).mean())
    audit["microstructure_zero_fraction"] = micro_zero

    if oi_cols and max_oi_std < oi_std_threshold:
        warnings.warn(
            "WARNING: OI features have near-zero variance after build_v43_feature_matrix "
            f"(max std={max_oi_std:.2e}). Check OI:SYMBOL candle alignment to df_5m timestamps.",
            UserWarning,
            stacklevel=2,
        )
        audit["oi_alignment_warning"] = True

    if micro_cols:
        max_micro_zero = max(micro_zero.values()) if micro_zero else 0.0
        if max_micro_zero >= 0.80:
            warnings.warn(
                "WARNING: microstructure features mostly zero "
                f"({max_micro_zero * 100:.1f}% zeros). "
                "Provide V43_TICKER_SNAPSHOTS_CSV for bid/ask history.",
                UserWarning,
                stacklevel=2,
            )
            audit["microstructure_sparse_warning"] = True

    return list(feat_cols), audit


def _calibrator_scale_sufficient(
    calibrator: Any,
    meta_val_proba: np.ndarray,
    *,
    round_trip_cost: float,
    min_scale_fraction: float = 0.5,
) -> Tuple[bool, float]:
    """Return whether Ridge calibrator outputs span enough return scale for gate-5."""
    try:
        cal_out = np.asarray(
            calibrator.predict(meta_val_proba.reshape(-1, 1)),
            dtype=np.float64,
        ).ravel()
    except Exception:
        return False, 0.0
    max_abs = float(np.nanmax(np.abs(cal_out))) if cal_out.size else 0.0
    min_required = float(round_trip_cost) * float(min_scale_fraction)
    return max_abs >= min_required, max_abs


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
    gross_y_va: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Shared thresholding + validation metrics for meta or regressor-mean stacks."""
    long_p, short_p = resolve_validation_threshold_percentiles()
    min_thr = resolve_min_dynamic_threshold(round_trip_cost)
    dt_long = max(float(np.nanpercentile(val_pred, long_p)), min_thr, 1e-6)
    dt_short = min(float(np.nanpercentile(val_pred, short_p)), -min_thr, -1e-6)
    dt_short_mag = abs(dt_short)
    threshold_floor_applied = bool(
        dt_long >= min_thr - 1e-12 or dt_short_mag >= min_thr - 1e-12
    )
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
        "threshold_percentile": float(long_p),
        "short_threshold_percentile": float(short_p),
        "dynamic_threshold": dt_long,
        "short_threshold": dt_short_mag,
        "min_dynamic_threshold": float(min_thr),
        "threshold_floor_applied": threshold_floor_applied,
        "validation_rmse": float(np.sqrt(np.mean((val_pred - y_va) ** 2))),
        "validation_mae": float(np.mean(np.abs(val_pred - y_va))),
        "validation_corr": _safe_corr(val_pred, y_va),
        "validation_corr_gross": _safe_corr(val_pred, gross_y_va)
        if gross_y_va is not None
        else _safe_corr(val_pred, y_va),
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
    use_meta_stack: bool = False,
    gross_y_val: Optional[np.ndarray] = None,
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
        num_leaves=31,
        max_depth=6,
        min_child_samples=150,
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
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    lgbm_model.lgbm = lgb_inner
    lgbm_model.feature_cols = feat_cols

    ensemble = EnsembleModel()
    ensemble._ens_scaler = RobustScaler()
    X_train_s = ensemble._ens_scaler.fit_transform(X_train.values)
    X_val_s = ensemble._ens_scaler.transform(X_val.values)

    xgb = XGBRegressor(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        min_child_weight=15,
        gamma=0.1,
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
        max_depth=8,
        min_samples_leaf=150,
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
            gross_y_va=gross_y_val,
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

    scale_ok, cal_max_abs = _calibrator_scale_sufficient(
        calibrator,
        meta_val_proba,
        round_trip_cost=round_trip_cost,
    )
    calibrator_fallback = False
    if not scale_ok:
        warnings.warn(
            f"WARNING: Ridge calibrator max |output|={cal_max_abs:.6f} < "
            f"{round_trip_cost * 0.5:.6f} (50% round-trip). "
            "Falling back to regressor_mean for this horizon.",
            UserWarning,
            stacklevel=2,
        )
        calibrator_fallback = True
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
        inference_path = "regressor_mean"
        threshold_source = "validation_regressor_mean_percentile"
        label_mode_out = "regressor_mean_stack_calibrator_fallback"
        meta_auc = None
    else:
        ensemble.meta = meta_clf
        ensemble.calibrator = calibrator
        val_pred = np.asarray(
            ensemble.predict(X_val.values, X_df=X_val), dtype=np.float64
        ).ravel()
        inference_path = "meta_calibrator"
        threshold_source = "validation_meta_prediction_percentile"
        label_mode_out = label_mode
        try:
            from sklearn.metrics import roc_auc_score

            if label_mode == "cost_aware_tradable" and int(auc_mask.sum()) > 10:
                meta_auc = float(
                    roc_auc_score(y_meta_va[auc_mask], meta_val_proba[auc_mask])
                )
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
        inference_path=inference_path,
        label_mode=label_mode_out,
        tradable_frac=tradable_frac,
        threshold_source=threshold_source,
        meta_auc=meta_auc,
        gross_y_va=gross_y_val,
    )
    if calibrator_fallback:
        validation_metrics["calibrator_scale_fallback"] = True
        validation_metrics["calibrator_max_abs_output"] = cal_max_abs

    return ensemble, validation_metrics


def train_multihead_from_feature_matrix(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    feat_cols: Optional[List[str]] = None,
    validation_fraction: float = 0.15,
    rng: int = 42,
    maker_fee: float = 0.0002,
    slippage: float = 0.0003,
    leverage: int = 3,
    cost_aware_labels: bool = False,
    use_meta_stack: bool = False,
) -> Tuple[MultiHeadBundle, Dict[str, Any]]:
    """Train all horizon heads on shared features.

    When ``use_meta_stack`` is False, each head uses the mean of base regressors only
    (``inference_path=regressor_mean``) with no LGBMClassifier meta-learner or Ridge calibrator.

    ``leverage`` is stored in ``runtime_cost_assumptions`` metadata only; labels and
    Gate-5 edge math use 1x price returns (``round_trip_cost_includes_leverage=False``).
    Position sizing applies leverage separately via
    ``jacksparrow_v43_max_position_pct * jacksparrow_v43_leverage_assumption``.
    """
    cols = list(feat_cols or V43_CANONICAL_FEATURES)
    missing = [c for c in cols if c not in df_feat.columns]
    if missing:
        raise ValueError(f"feature matrix missing columns: {missing[:8]}")

    cols, derivatives_audit = _audit_sparse_derivatives_features(df_feat, cols)

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
        y_gross_full = build_forward_labels(close, fb)
        work = df_feat[cols].copy()
        work["target"] = y_raw.values
        work["target_gross"] = y_gross_full.values
        work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=["target"])
        if len(work) < 500 and cost_aware_labels:
            y_gross = build_forward_labels(close, fb)
            work = df_feat[cols].copy()
            work["target"] = y_gross.values
            work["target_gross"] = y_gross.values
            work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=["target"])
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
        y_gross_val = work.iloc[val_idx]["target_gross"].values.astype(np.float64)

        ensemble, vm = train_horizon_ensemble(
            X_train,
            y_train,
            X_val,
            y_val,
            rng=rng + fb,
            round_trip_cost=round_trip_cost,
            forward_bars=fb,
            use_meta_stack=use_meta_stack,
            gross_y_val=y_gross_val,
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
        "primary_execution_horizon_bars": int(
            os.environ.get(
                "V43_PRIMARY_EXECUTION_HORIZON_BARS",
                str(V43_FORWARD_TARGET_BARS_DEFAULT),
            )
        ),
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
        "training_feature_audit": derivatives_audit,
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


def compute_vol_sample_weights(
    df_feat: pd.DataFrame,
    *,
    atr_col: str = "atr_pct",
    window: int = 200,
    clip_low: float = 0.5,
    clip_high: float = 3.0,
) -> pd.Series:
    """Volatility-proportional sample weights (Gap 5)."""
    atr = pd.to_numeric(df_feat[atr_col], errors="coerce")
    med = atr.rolling(window, min_periods=50).median()
    w = (atr / med).clip(clip_low, clip_high)
    return w.fillna(1.0)


def subsample_stride_indices(n_rows: int, *, stride: int) -> np.ndarray:
    """Reduce within-train label overlap (Gap 6B)."""
    st = max(1, int(stride))
    return np.arange(0, n_rows, st, dtype=np.int64)


def align_close_to_feature_matrix(
    df_feat: pd.DataFrame,
    close: pd.Series,
) -> pd.Series:
    """Align close prices to feature matrix rows (Colab-safe when index types differ).

    ``df_feat`` typically uses a RangeIndex while ``close`` is indexed by bar
    timestamps. When a ``timestamp`` column exists on ``df_feat``, reindex by
    that column and return a series indexed like ``df_feat``.
    """
    c = pd.to_numeric(close, errors="coerce").astype(float)
    if "timestamp" in df_feat.columns:
        ts = pd.to_datetime(df_feat["timestamp"], utc=True)
        if isinstance(c.index, pd.DatetimeIndex):
            c_idx = c.index.tz_convert("UTC") if c.index.tz is not None else c.index.tz_localize("UTC")
        else:
            c_idx = pd.to_datetime(c.index, utc=True)
        mapped = c.copy()
        mapped.index = c_idx
        aligned = mapped.reindex(ts)
        return pd.Series(aligned.values, index=df_feat.index)
    if len(c) == len(df_feat):
        return pd.Series(c.values, index=df_feat.index)
    aligned = c.reindex(df_feat.index)
    if int(aligned.notna().sum()) == 0 and len(c) == len(df_feat):
        return pd.Series(c.values, index=df_feat.index)
    return aligned


def feature_correlation_report(
    df_feat: pd.DataFrame,
    feat_cols: List[str],
    *,
    threshold: float = 0.85,
) -> Dict[str, Any]:
    """Pairwise Spearman correlation; flag highly redundant pairs (Gap 3)."""
    cols = [c for c in feat_cols if c in df_feat.columns]
    sub = df_feat[cols].replace([np.inf, -np.inf], np.nan).dropna()
    if sub.empty or len(cols) < 2:
        return {"pairs_flagged": [], "threshold": threshold}
    corr = sub.corr(method="spearman")
    flagged: List[Dict[str, Any]] = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            try:
                r = float(corr.loc[a, b])
            except (TypeError, ValueError, KeyError):
                continue
            if abs(r) >= threshold:
                flagged.append({"a": a, "b": b, "spearman": r})
    return {"pairs_flagged": flagged, "threshold": threshold, "n_features": len(cols)}


def training_feature_stats_dict(
    df_feat: pd.DataFrame,
    feat_cols: List[str],
) -> Dict[str, Dict[str, float]]:
    """Mean/std per feature for runtime drift baseline (Gap 7)."""
    out: Dict[str, Dict[str, float]] = {}
    for col in feat_cols:
        if col not in df_feat.columns:
            continue
        s = pd.to_numeric(df_feat[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if s.notna().sum() < 10:
            continue
        out[col] = {"mean": float(s.mean()), "std": float(s.std()) if s.std() > 0 else 1e-8}
    return out


def extract_lgbm_importances(
    estimator: Any,
    feature_cols: List[str],
    *,
    top_k: int = 15,
) -> Dict[str, float]:
    """LightGBM gain importances keyed by feature name."""
    imp = getattr(estimator, "feature_importances_", None)
    if imp is None:
        inner = getattr(estimator, "lgbm", None) or getattr(estimator, "classifier", None)
        imp = getattr(inner, "feature_importances_", None) if inner is not None else None
    if imp is None:
        return {}
    pairs = sorted(
        zip(feature_cols, np.asarray(imp, dtype=np.float64)),
        key=lambda x: -x[1],
    )
    return {k: float(v) for k, v in pairs[:top_k]}


def extract_head_importances(
    bundle: MultiHeadBundle,
    *,
    top_k: int = 15,
) -> Dict[str, Dict[str, float]]:
    """Per-horizon LGBM + state-head importances (Gap 1)."""
    out: Dict[str, Dict[str, float]] = {}
    for fb in bundle.head_bars():
        ens = bundle.get_head(fb)
        if ens is None:
            continue
        lgbm = getattr(ens, "lgbm_model", None)
        if lgbm is not None:
            cols = list(getattr(lgbm, "feature_cols", None) or [])
            inner = getattr(lgbm, "lgbm", None)
            if cols and inner is not None:
                out[f"horizon_{fb}"] = extract_lgbm_importances(inner, cols, top_k=top_k)
    for key in bundle.state_head_keys():
        sh = bundle.get_state_head(key)
        if sh is None:
            continue
        cols = list(getattr(sh, "feature_cols", None) or [])
        clf = getattr(sh, "classifier", None)
        if cols and clf is not None:
            out[f"state_{key}"] = extract_lgbm_importances(clf, cols, top_k=top_k)
    return out


def _state_classifier_params(*, rng: int, n_classes: int) -> Dict[str, Any]:
    base = {
        "n_estimators": 250,
        "num_leaves": 23,
        "min_child_samples": 90,
        "reg_lambda": 2.0,
        "reg_alpha": 0.1,
        "learning_rate": 0.045,
        "random_state": rng,
        "verbose": -1,
    }
    if n_classes > 2:
        base["class_weight"] = "balanced"
    return base


def _fit_state_classifier(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    rng: int,
    n_classes: int,
    sample_weight: Optional[np.ndarray] = None,
    scale_pos_weight: Optional[float] = None,
) -> Any:
    params = _state_classifier_params(rng=rng, n_classes=n_classes)
    if scale_pos_weight is not None and n_classes == 2:
        params["scale_pos_weight"] = float(scale_pos_weight)
    clf = LGBMClassifier(**params)
    sw = sample_weight
    if sw is not None:
        try:
            clf.fit(X_train, y_train, sample_weight=sw, eval_set=[(X_val, y_val)])
        except TypeError:
            _fit_lgb_sklearn_compat(
                clf, X_train, y_train, eval_set=[(X_val, y_val)]
            )
    else:
        _fit_lgb_sklearn_compat(
            clf, X_train, y_train, eval_set=[(X_val, y_val)]
        )
    return clf


def _balanced_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    from sklearn.metrics import balanced_accuracy_score

    return float(balanced_accuracy_score(y_true, y_pred))


def train_regime_head(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    rng: int = 42,
    sample_weight: Optional[np.ndarray] = None,
) -> Tuple[StateHeadModel, Dict[str, Any]]:
    """4-class regime classifier."""
    class_to_int = {c: i for i, c in enumerate(V43_REGIME_CLASSES)}
    y_tr = y_train.map(class_to_int).astype(int).values
    y_va = y_val.map(class_to_int).astype(int).values
    feat_cols = list(X_train.columns)
    model = StateHeadModel()
    model.scaler = RobustScaler()
    X_tr = model.scaler.fit_transform(X_train.values)
    X_va = model.scaler.transform(X_val.values)
    sw = sample_weight
    clf = _fit_state_classifier(
        X_tr, y_tr, X_va, y_va, rng=rng, n_classes=4, sample_weight=sw
    )
    model.classifier = clf
    model.feature_cols = feat_cols
    model.head_key = "regime"
    model.head_type = "regime"
    model.classes_ = list(V43_REGIME_CLASSES)
    model._is_fitted = True

    proba_va = _predict_lgb_proba_compat(clf, X_va)
    y_pred = np.argmax(proba_va, axis=1) if proba_va.ndim == 2 else (proba_va > 0.5).astype(int)
    bal_acc = _balanced_accuracy(y_va, y_pred)
    per_class: Dict[str, float] = {}
    for i, cls in enumerate(V43_REGIME_CLASSES):
        mask = y_va == i
        if mask.any():
            per_class[cls] = float((y_pred[mask] == i).mean())

    metrics = {
        "head_key": "regime",
        "head_type": "regime",
        "balanced_accuracy": bal_acc,
        "per_class_recall": per_class,
        "n_train": int(len(y_tr)),
        "n_val": int(len(y_va)),
    }
    return model, metrics


def train_vol_expansion_head(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    rng: int = 42,
    sample_weight: Optional[np.ndarray] = None,
    scale_pos_weight: float = 4.0,
) -> Tuple[StateHeadModel, Dict[str, Any]]:
    """Binary volatility expansion classifier."""
    y_tr = y_train.astype(int).values
    y_va = y_val.astype(int).values
    feat_cols = list(X_train.columns)
    model = StateHeadModel()
    model.scaler = RobustScaler()
    X_tr = model.scaler.fit_transform(X_train.values)
    X_va = model.scaler.transform(X_val.values)
    clf = _fit_state_classifier(
        X_tr,
        y_tr,
        X_va,
        y_va,
        rng=rng,
        n_classes=2,
        sample_weight=sample_weight,
        scale_pos_weight=scale_pos_weight,
    )
    model.classifier = clf
    model.feature_cols = feat_cols
    model.head_key = "vol_expansion"
    model.head_type = "binary"
    model.classes_ = ["no_expansion", "expansion"]
    model._is_fitted = True

    proba_va = _predict_lgb_proba_compat(clf, X_va)[:, 1]
    try:
        from sklearn.metrics import roc_auc_score

        auc = float(roc_auc_score(y_va, proba_va))
    except Exception:
        auc = 0.5
    metrics = {
        "head_key": "vol_expansion",
        "head_type": "binary",
        "validation_auc": auc,
        "expansion_rate_val": float(y_va.mean()) if len(y_va) else 0.0,
        "n_train": int(len(y_tr)),
        "n_val": int(len(y_va)),
    }
    return model, metrics


def train_trade_quality_head(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    rng: int = 42,
    sample_weight: Optional[np.ndarray] = None,
) -> Tuple[StateHeadModel, Dict[str, Any]]:
    """Binary trade-quality (TP-first) classifier."""
    y_tr = y_train.astype(int).values
    y_va = y_val.astype(int).values
    feat_cols = list(X_train.columns)
    model = StateHeadModel()
    model.scaler = RobustScaler()
    X_tr = model.scaler.fit_transform(X_train.values)
    X_va = model.scaler.transform(X_val.values)
    clf = _fit_state_classifier(
        X_tr, y_tr, X_va, y_va, rng=rng, n_classes=2, sample_weight=sample_weight
    )
    model.classifier = clf
    model.feature_cols = feat_cols
    model.head_key = "trade_quality"
    model.head_type = "binary"
    model.classes_ = ["sl_first", "tp_first"]
    model._is_fitted = True

    proba_va = _predict_lgb_proba_compat(clf, X_va)[:, 1]
    try:
        from sklearn.metrics import roc_auc_score

        auc = float(roc_auc_score(y_va, proba_va))
    except Exception:
        auc = 0.5
    metrics = {
        "head_key": "trade_quality",
        "head_type": "binary",
        "validation_auc": auc,
        "tp_first_rate_val": float(y_va.mean()) if len(y_va) else 0.0,
        "n_train": int(len(y_tr)),
        "n_val": int(len(y_va)),
    }
    return model, metrics


def train_state_heads_from_feature_matrix(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    feat_cols: Optional[List[str]] = None,
    validation_fraction: float = 0.15,
    rng: int = 42,
    embargo_bars: int = 12,
    skip_bars: Optional[int] = None,
    sample_weight_series: Optional[pd.Series] = None,
    tier_masks: Optional[Dict[str, List[str]]] = None,
    trade_quality_forward_bars: int = 12,
    take_profit_pct: float = 0.012,
    stop_loss_pct: float = 0.008,
) -> Tuple[Dict[str, StateHeadModel], Dict[str, Any]]:
    """Train regime, vol-expansion, and trade-quality state heads."""
    masks = tier_masks or {
        k: list(v) for k, v in V43_STATE_HEAD_FEATURE_TIERS.items()
    }
    close_aligned = align_close_to_feature_matrix(df_feat, close)
    if int(close_aligned.notna().sum()) < 500:
        raise ValueError(
            "close series could not be aligned to df_feat rows "
            f"(valid close rows={int(close_aligned.notna().sum())}). "
            "Ensure close is indexed by bar timestamps matching df_feat['timestamp']."
        )

    regime_raw, regime_stats = build_regime_labels(df_feat)
    vol_raw, vol_stats = build_vol_expansion_labels(
        close_aligned, forward_bars=embargo_bars
    )
    tq_raw, tq_stats = build_trade_quality_labels(
        close_aligned,
        forward_bars=trade_quality_forward_bars,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
    )

    state_models: Dict[str, StateHeadModel] = {}
    state_meta: Dict[str, Any] = {
        "embargo_bars": int(embargo_bars),
        "label_stats": {
            "regime": regime_stats,
            "vol_expansion": vol_stats,
            "trade_quality": tq_stats,
        },
        "trade_quality_params": {
            "forward_bars": trade_quality_forward_bars,
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
        },
    }

    label_specs = [
        ("regime", regime_raw, masks.get("regime", list(V43_STATE_HEAD_FEATURE_TIERS["regime"]))),
        ("vol_expansion", vol_raw, masks.get("vol_expansion", list(V43_STATE_HEAD_FEATURE_TIERS["vol_expansion"]))),
        ("trade_quality", tq_raw, masks.get("trade_quality", list(V43_STATE_HEAD_FEATURE_TIERS["trade_quality"]))),
    ]

    trainers = {
        "regime": train_regime_head,
        "vol_expansion": train_vol_expansion_head,
        "trade_quality": train_trade_quality_head,
    }

    for head_key, y_series, head_feats in label_specs:
        use_feats = [c for c in head_feats if c in df_feat.columns]
        if not use_feats:
            use_feats = list(feat_cols or V43_CANONICAL_FEATURES)
            use_feats = [c for c in use_feats if c in df_feat.columns]
        work = df_feat[use_feats].copy()
        work["target"] = y_series.reindex(work.index).values
        work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=["target"])
        if len(work) < 500:
            raise ValueError(f"insufficient rows for state head {head_key}: {len(work)}")

        train_idx, _, val_idx, split_meta = chronological_split_indices(
            len(work),
            validation_fraction=validation_fraction,
            embargo_bars=embargo_bars,
        )
        if skip_bars is not None and skip_bars > 1:
            stride_idx = subsample_stride_indices(len(work), stride=skip_bars)
            train_idx = train_idx[np.isin(train_idx, stride_idx)]

        X = work[use_feats]
        y = work["target"]
        sw_train = None
        if sample_weight_series is not None:
            sw = sample_weight_series.reindex(work.index).fillna(1.0).values
            sw_train = sw[train_idx]

        trainer = trainers[head_key]
        if head_key == "vol_expansion":
            model, metrics = trainer(
                X.iloc[train_idx],
                y.iloc[train_idx],
                X.iloc[val_idx],
                y.iloc[val_idx],
                rng=rng + 100,
                sample_weight=sw_train,
                scale_pos_weight=4.0,
            )
        else:
            model, metrics = trainer(
                X.iloc[train_idx],
                y.iloc[train_idx],
                X.iloc[val_idx],
                y.iloc[val_idx],
                rng=rng + 100,
                sample_weight=sw_train,
            )
        metrics["split"] = split_meta
        metrics["feature_cols"] = use_feats
        state_models[head_key] = model
        state_meta[head_key] = metrics

    return state_models, state_meta


def walk_forward_fold_indices(
    n_rows: int,
    *,
    n_folds: int = 3,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Phase 5: expanding-window walk-forward train/val index pairs."""
    n = int(n_rows)
    folds = max(2, int(n_folds))
    chunk = max(1, n // (folds + 1))
    pairs: List[Tuple[np.ndarray, np.ndarray]] = []
    for k in range(1, folds + 1):
        val_start = min(n - chunk, chunk * (k + 1))
        val_end = min(n, val_start + chunk)
        train_end = max(0, val_start - chunk)
        if train_end < 200 or val_end <= val_start:
            continue
        pairs.append(
            (
                np.arange(0, train_end, dtype=np.int64),
                np.arange(val_start, val_end, dtype=np.int64),
            )
        )
    return pairs
