"""Pickle compatibility shims for JackSparrow v43 artifacts.

The v43 model bundle (``model_artifact_v43.pkl``, ``regime_models_v43.pkl``,
``feature_engineer.pkl``) was produced by a Colab notebook where the classes
``EnsembleModel``, ``LGBMModel`` and ``FeatureEngineer`` live in ``__main__``.
When ``joblib.load`` runs inside the agent, the unpickler cannot find those
names because the notebook scope is gone, raising::

    AttributeError: Can't get attribute 'EnsembleModel' on <module '__main__'>

This module solves that by:

1. Defining minimal class stubs whose ``__setstate__`` accepts arbitrary state
   from the pickled instance.
2. Implementing ``predict``/``predict_uncertainty``/``transform`` on the stubs
   that delegate to the standard sklearn/lightgbm/xgboost objects loaded into
   ``self.lgbm`` / ``self.xgb`` / ``self.rf`` / ``self.mlp`` / ``self.scaler``
   / ``self.meta`` / ``self.calibrator`` (mirroring the v27/v28/v39 ensemble
   contracts that the v43 artifact is derived from).
3. Aliasing the stubs into ``sys.modules['__main__']`` at import time so the
   pickle loader resolves ``__main__.EnsembleModel`` etc. to these stubs.

The shims are intentionally minimal: they read instance state populated by the
unpickler (RobustScaler, LightGBM/XGB classifiers, RF, optional meta + calibrator,
optional feature_engineer pipeline). They do **not** retrain or modify state.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:  # pragma: no cover
    import structlog

    _logger = structlog.get_logger()
except Exception:  # pragma: no cover
    import logging

    _logger = logging.getLogger("v43_pickle_shims")


def _safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # pragma: no cover
        _logger.warning("v43_shim_call_failed: %s", exc)
        return None


class _StateDictMixin:
    """Default __setstate__ that accepts an arbitrary attribute dict."""

    def __setstate__(self, state: Dict[str, Any]) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)


class FeatureEngineer(_StateDictMixin):
    """Pickle shim for the v43 ``FeatureEngineer`` class.

    The v43 artifact only stores ``self.columns`` (the 40 selected feature
    names). Its ``transform()`` method in the original Colab notebook calls
    ``build_feature_matrix(df_5m, df_15m, df_1h, df_funding, for_training=...)``
    — a *module-level* function that is **not** captured by ``joblib.dump``
    of the instance.

    To make ``fe.transform(...)`` work in the agent, the bundle must be
    accompanied by either:

      1. A re-exported artifact pickled with ``cloudpickle`` (captures
         closures), or
      2. A ``build_feature_matrix`` callable injected at import time via
         :func:`set_v43_build_feature_matrix` so the shim can delegate to it.

    Without one of these, ``transform()`` raises a clear ``RuntimeError``
    explaining the missing dependency.
    """

    columns: Optional[List[str]] = None

    def __init__(self) -> None:
        self.columns = None

    def transform(
        self,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        df_1h: Optional[pd.DataFrame] = None,
        df_funding: Optional[pd.DataFrame] = None,
        df_oi: Optional[pd.DataFrame] = None,
        df_mark: Optional[pd.DataFrame] = None,
        include_target: bool = False,
    ) -> pd.DataFrame:
        # 1) Delegate to a callable stored on the instance (closures captured).
        for cand in ("_transform", "pipeline", "_pipeline", "transform_impl"):
            fn = getattr(self, cand, None)
            if callable(fn):
                try:
                    out = fn(
                        df_5m,
                        df_15m,
                        df_1h,
                        df_funding,
                        df_oi=df_oi,
                        df_mark=df_mark,
                        include_target=include_target,
                    )
                except TypeError:
                    try:
                        out = fn(
                            df_5m,
                            df_15m,
                            df_1h,
                            df_funding,
                            df_oi=df_oi,
                            include_target=include_target,
                        )
                    except TypeError:
                        out = fn(df_5m, df_15m, df_1h, df_funding, include_target=include_target)
                if isinstance(out, pd.DataFrame):
                    return out
        # 2) Delegate to a registered ``build_feature_matrix`` function.
        bfm = _BUILD_FEATURE_MATRIX
        if callable(bfm):
            try:
                out = bfm(
                    df_5m,
                    df_15m,
                    df_1h,
                    df_funding,
                    df_oi=df_oi,
                    df_mark=df_mark,
                    for_training=include_target,
                )
            except TypeError:
                try:
                    out = bfm(
                        df_5m,
                        df_15m,
                        df_1h,
                        df_funding,
                        df_oi=df_oi,
                        for_training=include_target,
                    )
                except TypeError:
                    out = bfm(df_5m, df_15m, df_1h, df_funding, for_training=include_target)
            if not isinstance(out, pd.DataFrame):
                raise RuntimeError(
                    "v43 FeatureEngineer shim: registered build_feature_matrix "
                    "did not return a DataFrame."
                )
            cols = list(self.columns or [])
            if cols:
                missing = [c for c in cols if c not in out.columns]
                if missing:
                    raise ValueError(
                        f"v43 FeatureEngineer shim: build_feature_matrix output "
                        f"missing required columns: {missing[:8]}"
                    )
                keep = cols + [c for c in ("timestamp", "regime_label") if c in out.columns]
                if include_target and "target" in out.columns:
                    keep.append("target")
                return out[keep]
            return out
        raise RuntimeError(
            "v43 FeatureEngineer shim: no usable transform pipeline. The "
            "feature_engineer.pkl was exported without its build_feature_matrix "
            "closure. Provide it via "
            "agent.models.v43_pickle_shims.set_v43_build_feature_matrix(fn) "
            "during agent startup, or re-export feature_engineer.pkl with "
            "cloudpickle so the closure is captured."
        )


_BUILD_FEATURE_MATRIX: Optional[Any] = None


def set_v43_build_feature_matrix(fn: Any) -> None:
    """Register a v43 ``build_feature_matrix(...)`` implementation.

    Signature: ``build_v43_feature_matrix(df_5m, df_15m, df_1h, df_funding,
    df_oi=None, df_mark=None, for_training=False, ...)``. Required when the pickle did not
    capture its closure.
    """
    global _BUILD_FEATURE_MATRIX
    _BUILD_FEATURE_MATRIX = fn


class LGBMModel(_StateDictMixin):
    """Pickle shim for the v37/v39-style single-model classifier wrapper.

    Stored attributes typically include ``scaler`` (RobustScaler), ``lgbm``
    (lightgbm.LGBMClassifier), and optionally ``rf_unc``, ``feature_cols``,
    ``dynamic_threshold``, ``regime_thresholds``.
    """

    def __init__(self) -> None:
        self.scaler = None
        self.lgbm = None
        self.rf_unc = None
        self.feature_cols: Optional[List[str]] = None
        self.dynamic_threshold: Optional[float] = None
        self.regime_thresholds: Dict[str, float] = {}

    @property
    def threshold_long(self) -> Optional[float]:
        return self.dynamic_threshold

    def _scale(self, X: np.ndarray) -> np.ndarray:
        Xa = np.asarray(X, dtype=np.float32)
        scaler = getattr(self, "scaler", None) or getattr(self, "_ens_scaler", None)
        if scaler is not None and hasattr(scaler, "transform"):
            return np.asarray(scaler.transform(Xa), dtype=np.float32)
        return Xa

    @staticmethod
    def _est_predict(est: Any, Xs: np.ndarray) -> Optional[np.ndarray]:
        if est is None:
            return None
        # Detect regressor vs classifier via sklearn's _estimator_type.
        etype = getattr(est, "_estimator_type", None)
        is_regressor = (etype == "regressor") or (
            hasattr(est, "predict") and not hasattr(est, "predict_proba")
        )
        if is_regressor:
            try:
                return np.asarray(est.predict(Xs), dtype=np.float64).ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_regressor_predict_failed",
                                clf=type(est).__name__, err=str(exc))
                return None
        if hasattr(est, "predict_proba"):
            try:
                p = np.asarray(est.predict_proba(Xs), dtype=np.float64)
                if p.ndim == 2 and p.shape[1] >= 2:
                    return p[:, 1]
                return p.ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_clf_predict_proba_failed",
                                clf=type(est).__name__, err=str(exc))
                return None
        if hasattr(est, "predict"):
            try:
                return np.asarray(est.predict(Xs), dtype=np.float64).ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_predict_fallback_failed",
                                clf=type(est).__name__, err=str(exc))
                return None
        return None

    def predict(self, X: np.ndarray, X_df: Optional[pd.DataFrame] = None) -> np.ndarray:
        Xs = self._scale(X)
        inner = getattr(self, "lgbm", None)
        out = self._est_predict(inner, Xs)
        if out is None:
            raise RuntimeError(
                f"v43 LGBMModel shim: no usable inner lightgbm estimator in state "
                f"(inner_type={type(inner).__name__})."
            )
        return np.asarray(out, dtype=np.float64)

    def predict_proba(self, X: np.ndarray, X_df: Optional[pd.DataFrame] = None) -> np.ndarray:
        return self.predict(X, X_df=X_df)

    def predict_uncertainty(
        self, X: np.ndarray, X_df: Optional[pd.DataFrame] = None
    ) -> np.ndarray:
        Xs = self._scale(X)
        rf_unc = getattr(self, "rf_unc", None)
        rf_unc_pred = self._est_predict(rf_unc, Xs)
        if rf_unc_pred is not None and rf_unc_pred.size:
            return np.abs(rf_unc_pred - 0.5)
        inner = getattr(self, "lgbm", None)
        inner_pred = self._est_predict(inner, Xs)
        if inner_pred is not None and inner_pred.size:
            return np.abs(inner_pred - 0.5) * 0.5
        return np.full(Xs.shape[0], 0.05, dtype=np.float64)


class MultiHeadBundle(_StateDictMixin):
    """Single-bundle container for intraday multi-horizon ensembles (2/6/12/24 bars)."""

    def __init__(self) -> None:
        self.horizon_models: Dict[int, Any] = {}
        self._is_fitted: bool = False

    def set_head(self, forward_bars: int, model: Any) -> None:
        self.horizon_models[int(forward_bars)] = model
        self._is_fitted = True

    def get_head(self, forward_bars: int) -> Optional[Any]:
        return self.horizon_models.get(int(forward_bars))

    def head_bars(self) -> List[int]:
        return sorted(int(k) for k in self.horizon_models.keys())

    def predict_head(
        self,
        forward_bars: int,
        X: np.ndarray,
        X_df: Optional[pd.DataFrame] = None,
    ) -> np.ndarray:
        m = self.get_head(forward_bars)
        if m is None:
            raise KeyError(f"multi-head bundle missing horizon forward_bars={forward_bars}")
        pred_fn = getattr(m, "predict", None)
        if pred_fn is None:
            raise RuntimeError(f"head model for {forward_bars} has no predict()")
        out = pred_fn(X, X_df=X_df)
        return np.asarray(out, dtype=np.float64).ravel()


class EnsembleModel(_StateDictMixin):
    """Pickle shim for the v43 ensemble class.

    Confirmed v43 stored state (from runtime inspection):
      ``_ens_scaler`` (RobustScaler), ``lgbm_model`` (LGBMModel wrapper),
      ``xgb`` (XGBRegressor), ``rf`` (RandomForestRegressor),
      ``feature_cols`` (List[str]), ``threshold`` (float), ``_is_fitted`` (bool).

    **Default path (no meta):** base regressors are averaged; output is expected
    return on the simple-forward-return scale.

    **Pattern 3 meta-stacking (when ``meta`` + ``calibrator`` are set):**
      1. ``_base_predictions`` stacks LGBM/XGB/RF regressor outputs.
      2. ``meta.predict_proba(stack)[:, 1]`` yields direction probability in [0, 1].
      3. ``calibrator.predict(proba)`` maps probability back to expected-return scale
         so gate-5 edge-vs-cost math remains valid.

    ``predict()`` always returns values clipped to [-0.10, 0.10] as a safety backstop
    if the calibrator is missing or misconfigured.
    """

    def __init__(self) -> None:
        self._ens_scaler = None
        self.scaler = None  # legacy alias
        self.lgbm_model = None
        self.lgbm = None  # legacy alias
        self.xgb = None
        self.rf = None
        self.mlp = None
        self.meta = None
        self.calibrator = None
        self.feature_cols: Optional[List[str]] = None
        self.threshold: Optional[float] = None
        self.dynamic_threshold: Optional[float] = None
        self.short_threshold: Optional[float] = None
        self._regime_scaler = None
        self._regime_cols: List[str] = []
        self._is_fitted: bool = False

    @property
    def threshold_long(self) -> Optional[float]:
        return self.threshold if self.threshold is not None else self.dynamic_threshold

    def _scale(self, X: np.ndarray) -> np.ndarray:
        Xa = np.asarray(X, dtype=np.float32)
        scaler = getattr(self, "_ens_scaler", None) or getattr(self, "scaler", None)
        if scaler is not None and hasattr(scaler, "transform"):
            return np.asarray(scaler.transform(Xa), dtype=np.float32)
        return Xa

    @staticmethod
    def _estimator_predict(est: Any, Xs: np.ndarray) -> Optional[np.ndarray]:
        if est is None:
            return None
        # Wrapped LGBMModel (nested) — use its public predict.
        if hasattr(est, "predict") and est.__class__.__name__ == "LGBMModel":
            try:
                return np.asarray(est.predict(Xs), dtype=np.float64).ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_inner_lgbm_predict_failed: %s", exc)
                return None
        # Regressors (XGBRegressor, RandomForestRegressor, etc.).
        if hasattr(est, "predict") and not hasattr(est, "predict_proba"):
            try:
                return np.asarray(est.predict(Xs), dtype=np.float64).ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_regressor_predict_failed clf=%s: %s", type(est).__name__, exc)
                return None
        # Classifiers (legacy).
        if hasattr(est, "predict_proba"):
            try:
                p = np.asarray(est.predict_proba(Xs), dtype=np.float64)
                if p.ndim == 2 and p.shape[1] >= 2:
                    return p[:, 1]
                return p.ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_clf_predict_proba_failed clf=%s: %s", type(est).__name__, exc)
                return None
        return None

    def _base_predictions(self, X_raw: np.ndarray) -> np.ndarray:
        """Stacked predictions from all configured base estimators.

        ``X_raw`` is the *unscaled* input. Inner ``LGBMModel`` instances apply
        their own scaler internally, so we pass them raw X. The remaining base
        estimators (``xgb``, ``rf``, ``mlp``) consume ``_ens_scaler``-scaled X.
        """
        Xa = np.asarray(X_raw, dtype=np.float32)
        Xs = self._scale(Xa)
        cols: List[np.ndarray] = []
        lgbm_member = getattr(self, "lgbm_model", None) or getattr(self, "lgbm", None)
        if lgbm_member is not None:
            arr = self._estimator_predict(lgbm_member, Xa)
            if arr is not None:
                cols.append(arr)
        for attr in ("xgb", "rf", "mlp"):
            est = getattr(self, attr, None)
            arr = self._estimator_predict(est, Xs)
            if arr is not None:
                cols.append(arr)
        if not cols:
            raise RuntimeError(
                "v43 EnsembleModel shim: no usable base estimators in stored state."
            )
        return np.column_stack(cols)

    def predict(
        self,
        X: np.ndarray,
        X_df: Optional[pd.DataFrame] = None,
        *,
        inference_stack: Optional[str] = None,
    ) -> np.ndarray:
        stack = self._base_predictions(X)
        stack_mode = (
            inference_stack
            or getattr(self, "_inference_stack", None)
            or "meta_calibrator"
        )
        if stack_mode == "regressor_mean":
            out = stack.mean(axis=1)
            out = np.clip(np.asarray(out, dtype=np.float64), -0.10, 0.10)
            return out
        meta = getattr(self, "meta", None)
        # Legacy meta-learner path (v27/v28 classifier ensemble).
        if meta is not None and hasattr(meta, "predict_proba"):
            X_meta = stack
            cols = list(getattr(self, "_regime_cols", []) or [])
            scaler = getattr(self, "_regime_scaler", None)
            if cols and scaler is not None and X_df is not None and hasattr(X_df, "values"):
                try:
                    rv = X_df[cols].values.astype("float32")
                    rs = scaler.transform(rv.reshape(-1, len(cols)))
                    X_meta = np.hstack([stack, rs])
                except Exception as exc:  # pragma: no cover
                    _logger.warning("v43_shim_regime_meta_assemble_failed: %s", exc)
            try:
                out = meta.predict_proba(X_meta)[:, 1]
            except Exception as exc:
                _logger.warning("v43_shim_meta_failed: %s", exc)
                out = stack.mean(axis=1)
        else:
            # v43 path: simple unweighted mean of regressor expected returns.
            out = stack.mean(axis=1)
        cal = getattr(self, "calibrator", None)
        if cal is not None and hasattr(cal, "predict"):
            try:
                out = cal.predict(np.asarray(out, dtype=np.float64).reshape(-1, 1)).ravel()
            except Exception as exc:  # pragma: no cover
                _logger.warning("v43_shim_calibrator_failed: %s", exc)
        # Safety: clamp to sane expected-return range regardless of meta/calibrator state.
        out = np.clip(np.asarray(out, dtype=np.float64), -0.10, 0.10)
        return out

    def predict_proba(self, X: np.ndarray, X_df: Optional[pd.DataFrame] = None) -> np.ndarray:
        return self.predict(X, X_df=X_df)

    def predict_uncertainty(
        self, X: np.ndarray, X_df: Optional[pd.DataFrame] = None
    ) -> np.ndarray:
        try:
            stack = self._base_predictions(X)
            return stack.std(axis=1)
        except Exception as exc:
            _logger.warning("v43_shim_unc_failed: %s", exc)
            return np.full(np.asarray(X).shape[0], 0.05, dtype=np.float64)


def install_main_aliases() -> None:
    """Register shims as ``__main__.{EnsembleModel,LGBMModel,FeatureEngineer}``.

    Idempotent: only installs when the name is missing or maps to a previous
    install of the same shim. Never overwrites real classes that another
    module may have legitimately registered.
    """
    main_mod = sys.modules.get("__main__")
    if main_mod is None:
        return
    for cls in (EnsembleModel, LGBMModel, FeatureEngineer, MultiHeadBundle):
        existing = getattr(main_mod, cls.__name__, None)
        if existing is None or getattr(existing, "__module__", "") == __name__:
            try:
                cls.__module__ = "__main__"
            except Exception:  # pragma: no cover
                pass
            setattr(main_mod, cls.__name__, cls)


install_main_aliases()
