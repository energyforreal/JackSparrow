"""JackSparrow v43 inference helpers (thresholds, regime routing, uncertainty)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np


def _float_attr(obj: Any, name: str) -> Optional[float]:
    if obj is None:
        return None
    try:
        v = getattr(obj, name, None)
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def get_signal_threshold(
    regime: str,
    ensemble_model: Any,
    active_model: Any,
    *,
    floor: float = 0.005,
) -> float:
    """Resolve calibrated threshold for expected-return scale.

    Prefer ``lgbm_model.dynamic_threshold`` on the ensemble when present —
    it reflects OOF P75 calibration and must not be defeated by legacy
    ``regime_thresholds`` stuck at 0.05 (notebook export bug). Otherwise use
    regime-specific thresholds, then ``threshold`` / ``dynamic_threshold`` on
    the active model.
    """
    floor_f = float(floor)
    lgbm = getattr(ensemble_model, "lgbm_model", None)
    dt_ensemble = _float_attr(lgbm, "dynamic_threshold")

    m = active_model if active_model is not None else ensemble_model
    thr: Optional[float] = None

    rt = getattr(m, "regime_thresholds", None)
    if isinstance(rt, dict) and regime in rt:
        try:
            rv = float(rt[regime])
            # Ignore regime dict values that dominate calibrated dynamic threshold (classic bug).
            if dt_ensemble is not None and rv >= 0.04 and rv > dt_ensemble * 1.8:
                thr = dt_ensemble
            else:
                thr = rv
        except (TypeError, ValueError):
            thr = None

    if thr is None:
        for attr in ("threshold", "dynamic_threshold"):
            v = _float_attr(m, attr)
            if v is not None:
                thr = v
                break

    if thr is None:
        thr = dt_ensemble

    if thr is None:
        thr = floor_f

    # Soft floor only — never raise threshold above calibrated OOF value.
    return float(max(floor_f, thr))


def get_short_signal_threshold(
    regime: str,
    ensemble_model: Any,
    active_model: Any,
    *,
    floor: float = 0.005,
    long_threshold: Optional[float] = None,
) -> float:
    """Resolve short-side threshold (positive magnitude for ``proba < -thr``).

    When the artifact exports ``short_threshold`` (notebook P25 magnitude), use it.
    Otherwise fall back to the long threshold for backward-compatible symmetric gating.
    """
    floor_f = float(floor)
    m = active_model if active_model is not None else ensemble_model
    short_thr: Optional[float] = None
    for obj in (m, ensemble_model):
        if obj is None:
            continue
        v = _float_attr(obj, "short_threshold")
        if v is not None and v > 0:
            short_thr = abs(float(v))
            break
    if short_thr is None:
        short_thr = long_threshold
    if short_thr is None:
        short_thr = get_signal_threshold(
            regime, ensemble_model, active_model, floor=floor_f
        )
    return float(max(floor_f, short_thr))


def get_regime_model(
    regime: str,
    regime_models: Optional[Dict[str, Any]],
    global_model: Any,
) -> Optional[Any]:
    """Return sub-model for regime, global ensemble, or None if crisis (force flat).

    The v43 ``regime_models_v43.pkl`` stores entries shaped as
    ``{regime: {"model": LGBMModel, "metrics": dict, "n_rows": int}}``. This
    helper unwraps the inner ``model`` key so callers always receive a model
    object that supports ``predict``/``predict_uncertainty``.
    """
    if regime == "crisis":
        return None
    if regime_models and isinstance(regime_models, dict):
        sub = regime_models.get(regime)
        if isinstance(sub, dict):
            inner = sub.get("model")
            if inner is not None:
                return inner
            sub = None
        if sub is not None:
            return sub
    return global_model


def ensemble_predict_uncertainty(ensemble_model: Any, X_df: Any) -> float:
    """Std across sub-models when ``predict_uncertainty`` exists; else 0.05."""
    fn = getattr(ensemble_model, "predict_uncertainty", None)
    if not callable(fn):
        return 0.05
    try:
        X_mat = X_df.values if hasattr(X_df, "values") else np.asarray(X_df)
    except Exception:
        X_mat = X_df
    for call in (
        lambda: fn(X_mat, X_df=X_df),
        lambda: fn(X_mat),
        lambda: fn(X_df),
    ):
        try:
            arr = np.asarray(call(), dtype=np.float64).ravel()
            if arr.size:
                return float(max(arr[0], 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
    return 0.05


def uncertainty_scale(uncertainty: float) -> float:
    """Match LiveTrader: clip(1 - (u - 0.05) * 5, 0.3, 1.0)."""
    return float(np.clip(1.0 - (float(uncertainty) - 0.05) * 5.0, 0.3, 1.0))
