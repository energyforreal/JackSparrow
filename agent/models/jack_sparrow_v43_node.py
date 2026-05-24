"""MCP model node for JackSparrow v43 ensemble (joblib artifact + feature_engineer)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

try:
    import joblib  # type: ignore

    def _load(path: Path) -> Any:
        return joblib.load(path)
except Exception:  # pragma: no cover
    import pickle

    def _load(path: Path) -> Any:
        with open(path, "rb") as f:
            return pickle.load(f)

from agent.models import v43_pickle_shims as _v43_shims  # noqa: F401  ensures __main__ aliases
from agent.core.config import settings
from agent.core.v43_market_frames import closed_5m_bar_index
from agent.models.jacksparrow_v43_inference import (
    ensemble_predict_uncertainty,
    get_regime_model,
    get_short_signal_threshold,
    get_signal_threshold,
    uncertainty_scale,
)
from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from feature_store.jacksparrow_v43_contract import (
    audit_v43_metadata_promotion,
    validate_v43_metadata_compatibility,
    validate_v43_metadata_promotion,
)
from feature_store.jacksparrow_v43_horizon import (
    forward_bars_to_minutes,
    resolve_training_forward_bars,
)
from feature_store.jacksparrow_v43_multihead import (
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    head_thresholds,
    primary_execution_horizon_bars as meta_primary_horizon_bars,
)
from agent.models.v43_pickle_shims import MultiHeadBundle

logger = structlog.get_logger()

# Heuristic: classifier P(class=1) often sits in [0,1] with span < 0.85
_PROB_RETURN_SCALE = 0.04


def _v43_head_confidence(edge: float, threshold: float, unc_scale: float) -> float:
    """Map edge-over-threshold to [0,1] confidence, scaled by uncertainty."""
    thr = max(float(threshold), 1e-6)
    edge_ratio = min(1.0, abs(float(edge)) / thr)
    base = 0.25 + 0.75 * edge_ratio
    return float(min(1.0, max(0.0, base * float(unc_scale))))


def _ctx_dataframe(ctx: Dict[str, Any], primary_key: str, fallback_key: str) -> Optional[pd.DataFrame]:
    v = ctx.get(primary_key)
    if isinstance(v, pd.DataFrame):
        return v
    v = ctx.get(fallback_key)
    if isinstance(v, pd.DataFrame):
        return v
    return None


def _resolve_artifact_path(bundle_dir: Path) -> Path:
    preferred = (
        str(getattr(settings, "jacksparrow_v43_artifact_basename", "") or "").strip()
        or "model_artifact_v43_patched.pkl"
    )
    candidates = [
        bundle_dir / preferred,
        bundle_dir / "model_artifact_v43_patched.pkl",
        bundle_dir / "model_artifact_v43.pkl",
        bundle_dir / "model_artifact_v44_patched.pkl",
        bundle_dir / "model_artifact_v44.pkl",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        "v43/v44 artifact missing under "
        f"{bundle_dir}: tried {[p.name for p in candidates]}"
    )


def _apply_v43_threshold_patch(artifact: Dict[str, Any]) -> bool:
    """Fix notebook export bug: regime_thresholds stuck at ~0.05 while OOF P75 ~0.011."""
    model = artifact.get("model")
    if model is None:
        return False
    lgbm = getattr(model, "lgbm_model", None)
    if lgbm is None:
        return False
    try:
        dt_f = float(getattr(lgbm, "dynamic_threshold", None))
    except (TypeError, ValueError):
        return False
    rt = getattr(lgbm, "regime_thresholds", None)
    if not isinstance(rt, dict) or not rt:
        try:
            model.threshold = dt_f
        except Exception:
            pass
        return False
    vals: List[float] = []
    for v in rt.values():
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    if not vals:
        return False
    min_v = min(vals)
    # Classic bug: thresholds floored at 0.05 while predictions peak ~0.021
    if min_v >= 0.04 and dt_f < min_v * 0.8:
        new_rt = {str(k): dt_f for k in rt}
        lgbm.regime_thresholds = new_rt
        try:
            model.threshold = dt_f
        except Exception:
            pass
        rm = artifact.setdefault("regime_models", {})
        if isinstance(rm, dict) and "ranging" not in rm:
            rm["ranging"] = {"model": lgbm, "metrics": artifact.get("metrics") or {}}
        logger.info(
            "v43_threshold_patch_applied",
            dynamic_threshold=dt_f,
            prior_min_regime_thr=min_v,
        )
        return True
    return False


def _hydrate_ensemble_thresholds_from_metadata(ensemble: Any, meta: Dict[str, Any]) -> Dict[str, str]:
    """Apply metadata validation thresholds when the pickle omits them."""
    sources: Dict[str, str] = {}
    vm = meta.get("validation_metrics")
    if not isinstance(vm, dict):
        return sources
    dt_meta = vm.get("dynamic_threshold")
    st_meta = vm.get("short_threshold")
    if dt_meta is not None:
        try:
            dt_f = float(dt_meta)
            if getattr(ensemble, "threshold", None) is None and getattr(
                ensemble, "dynamic_threshold", None
            ) is None:
                ensemble.dynamic_threshold = dt_f
                sources["dynamic_threshold"] = "metadata"
            lgbm = getattr(ensemble, "lgbm_model", None)
            if lgbm is not None and getattr(lgbm, "dynamic_threshold", None) is None:
                lgbm.dynamic_threshold = dt_f
        except (TypeError, ValueError):
            pass
    if st_meta is not None:
        try:
            st_f = abs(float(st_meta))
            if getattr(ensemble, "short_threshold", None) is None:
                ensemble.short_threshold = st_f
                sources["short_threshold"] = "metadata"
        except (TypeError, ValueError):
            pass
    return sources


def _looks_like_classifier_probability(arr: np.ndarray) -> bool:
    if arr.size == 0:
        return False
    mn = float(np.min(arr))
    mx = float(np.max(arr))
    if mn >= 0.0 and mx <= 1.0 and (mx - mn) < 0.85:
        return True
    return False


def _coerce_probability_to_return_scale(arr: np.ndarray) -> np.ndarray:
    """Map P(class=1) in [0,1] to a small signed return proxy for gating."""
    return (np.asarray(arr, dtype=np.float64) - 0.5) * _PROB_RETURN_SCALE


def _sanitize_expected_return(
    arr: np.ndarray,
    *,
    active_model: Any,
    model_name: str,
) -> np.ndarray:
    out = np.asarray(arr, dtype=np.float64).ravel()
    if not _looks_like_classifier_probability(out):
        return out
    active_cls = type(active_model).__name__
    if active_cls == "EnsembleModel":
        return out
    logger.warning(
        "v43_classifier_probability_coerced_to_return_scale",
        model_name=model_name,
        active_type=active_cls,
        sample_min=float(np.min(out)),
        sample_max=float(np.max(out)),
    )
    return _coerce_probability_to_return_scale(out)


def _merge_regime_models(
    artifact: Dict[str, Any],
    file_dict: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Artifact regimes first; sidecar pickle wins on key overlap."""
    merged: Dict[str, Any] = {}
    art_rm = artifact.get("regime_models")
    if isinstance(art_rm, dict):
        merged.update(art_rm)
    if isinstance(file_dict, dict):
        merged.update(file_dict)
    return merged


class JackSparrowV43Node(MCPModelNode):
    """Loads v43 artifact (patched preferred), merges regimes, applies threshold patch."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        metadata_path: Path,
        feature_names: List[str],
    ) -> None:
        self._model_name = model_name
        self._model_version = model_version
        self._metadata_path = metadata_path
        self._feature_names = list(feature_names)
        self._bundle_dir = metadata_path.parent
        self._bundle_metadata: Dict[str, Any] = {}
        self._artifact: Dict[str, Any] = {}
        self._ensemble: Any = None
        self._multihead: Optional[MultiHeadBundle] = None
        self._fe: Any = None
        self._regime_models: Optional[Dict[str, Any]] = None
        self._artifact_path: Optional[Path] = None
        self._artifact_mtime_ref: float = 0.0
        self._initialized = False
        self._health = "unknown"
        self._call_count = 0
        self._error_count = 0
        # Serialize inference: sklearn/LGBM on one node are not safe under concurrent predict.
        self._predict_lock = asyncio.Lock()
        self._training_forward_bars: int = 6

    @property
    def training_forward_bars(self) -> int:
        return int(self._training_forward_bars)

    @classmethod
    def from_metadata_path(cls, metadata_path: Path) -> "JackSparrowV43Node":
        with metadata_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        validate_v43_metadata_compatibility(meta)
        name = str(meta.get("model_name") or "jacksparrow_v43_BTCUSD")
        ver = str(meta.get("version") or meta.get("version_tag") or "v43")
        feats = list(meta.get("features") or [])
        node = cls(
            model_name=name,
            model_version=ver,
            metadata_path=metadata_path,
            feature_names=feats,
        )
        node._training_forward_bars = resolve_training_forward_bars(
            meta,
            settings_fallback=int(
                getattr(settings, "jacksparrow_v43_forward_target_bars", 6) or 6
            ),
        )
        return node

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return "jacksparrow_v43"

    def _load_bundle_into_state(self) -> None:
        with self._metadata_path.open("r", encoding="utf-8") as f:
            self._bundle_metadata = json.load(f)
        self._training_forward_bars = resolve_training_forward_bars(
            self._bundle_metadata,
            settings_fallback=int(
                getattr(settings, "jacksparrow_v43_forward_target_bars", 6) or 6
            ),
        )
        cfg_bars = int(getattr(settings, "jacksparrow_v43_forward_target_bars", 6) or 6)
        if self._training_forward_bars != cfg_bars:
            logger.warning(
                "v43_horizon_bundle_config_mismatch",
                bundle_forward_bars=self._training_forward_bars,
                config_forward_target_bars=cfg_bars,
                hint="Retrain and promote a bundle with matching training_forward_bars, "
                "or align JACKSPARROW_V43_FORWARD_TARGET_BARS to the loaded metadata.",
            )
        strict_promo = bool(
            getattr(settings, "jacksparrow_v43_metadata_promotion_strict", False)
        )
        validate_v43_metadata_promotion(self._bundle_metadata, strict=strict_promo)
        promo_warnings = audit_v43_metadata_promotion(self._bundle_metadata)
        if promo_warnings:
            logger.warning(
                "v43_metadata_promotion_warnings",
                warnings=promo_warnings,
                strict=strict_promo,
            )

        art_path = _resolve_artifact_path(self._bundle_dir)
        self._artifact_path = art_path
        self._artifact = _load(art_path)
        model = self._artifact.get("model")
        if isinstance(model, MultiHeadBundle):
            self._multihead = model
        elif hasattr(model, "horizon_models") and isinstance(
            getattr(model, "horizon_models", None), dict
        ):
            self._multihead = model
        else:
            raise ValueError(
                "v43 artifact must contain MultiHeadBundle with horizon_models "
                f"(got {type(model).__name__}). Retrain with multi-head export."
            )
        stack_mode = str(
            getattr(settings, "jacksparrow_v43_inference_stack", "meta_calibrator")
            or "meta_calibrator"
        ).strip().lower()
        if stack_mode not in ("meta_calibrator", "regressor_mean"):
            logger.warning(
                "v43_inference_stack_unknown_fallback",
                requested=stack_mode,
                fallback="meta_calibrator",
            )
            stack_mode = "meta_calibrator"
        for fb in self._multihead.head_bars():
            head_model = self._multihead.get_head(fb)
            if head_model is not None:
                setattr(head_model, "_inference_stack", stack_mode)
                _apply_v43_threshold_patch({"model": head_model})
                hkey = next(
                    (k for k, b in V43_HORIZON_KEY_TO_BARS.items() if b == fb),
                    None,
                )
                if hkey:
                    dt, st = head_thresholds(self._bundle_metadata, hkey)
                    _hydrate_ensemble_thresholds_from_metadata(
                        head_model,
                        {
                            "validation_metrics": {
                                "dynamic_threshold": dt,
                                "short_threshold": st,
                            }
                        },
                    )
        self._training_forward_bars = meta_primary_horizon_bars(self._bundle_metadata)
        self._ensemble = self._multihead.get_head(self._training_forward_bars)
        if self._ensemble is None:
            raise ValueError(
                f"multi-head bundle missing primary head {self._training_forward_bars}"
            )
        self._fe = self._artifact.get("feature_engineer")
        if self._multihead is None or self._fe is None:
            raise ValueError("v43 artifact must contain multi-head 'model' and 'feature_engineer'")
        feats = self._artifact.get("features")
        if isinstance(feats, list) and feats:
            self._feature_names = [str(x) for x in feats]
        file_rm: Optional[Dict[str, Any]] = None
        reg_path = self._bundle_dir / "regime_models_v43.pkl"
        if reg_path.is_file():
            try:
                loaded = _load(reg_path)
                file_rm = loaded if isinstance(loaded, dict) else None
            except Exception as e:
                logger.warning("v43_regime_models_load_failed", error=str(e))
                file_rm = None
        self._regime_models = _merge_regime_models(self._artifact, file_rm)
        try:
            self._artifact_mtime_ref = float(art_path.stat().st_mtime)
        except OSError:
            self._artifact_mtime_ref = 0.0

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._load_bundle_into_state()
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "jacksparrow_v43_node_initialized",
            model_name=self._model_name,
            feature_count=len(self._feature_names),
            artifact=str(self._artifact_path),
            regime_keys=list(self._regime_models.keys()) if self._regime_models else [],
            inference_stack=str(
                getattr(settings, "jacksparrow_v43_inference_stack", "meta_calibrator")
            ),
        )

    async def _reload_if_stale(self) -> None:
        if not self._artifact_path or not self._artifact_path.is_file():
            return
        try:
            cur = float(self._artifact_path.stat().st_mtime)
        except OSError:
            return
        if cur > self._artifact_mtime_ref:
            logger.info(
                "jacksparrow_v43_hot_reload",
                path=str(self._artifact_path),
                old_mtime=self._artifact_mtime_ref,
                new_mtime=cur,
            )
            self._load_bundle_into_state()
            self._artifact_mtime_ref = cur

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "version": self._model_version,
            "model_type": self.model_type,
            "features_required": list(self._feature_names),
            "feature_list": list(self._feature_names),
            "description": "JackSparrow v43 dedicated ensemble (closed-bar inference)",
            "metadata_path": str(self._metadata_path),
            "artifact_path": str(self._artifact_path) if self._artifact_path else None,
        }

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
        }

    def _predict_active(self, active: Any, X: np.ndarray, X_df: pd.DataFrame) -> np.ndarray:
        pred_fn = getattr(active, "predict", None)
        if pred_fn is None:
            pred_fn = getattr(active, "predict_proba", None)
            if pred_fn is None:
                raise RuntimeError("active model has no predict/predict_proba")
        last_err: Optional[BaseException] = None
        for call in (
            lambda: pred_fn(X, X_df=X_df),
            lambda: pred_fn(X_df),
            lambda: pred_fn(X),
        ):
            try:
                out = call()
                arr = np.asarray(out, dtype=np.float64)
                if arr.ndim == 2 and arr.shape[1] >= 2:
                    arr = arr[:, 1]
                return _sanitize_expected_return(
                    arr.ravel(),
                    active_model=active,
                    model_name=self._model_name,
                )
            except (TypeError, ValueError) as exc:
                last_err = exc
                continue
        if last_err is not None:
            raise last_err
        raise RuntimeError("active model predict raised no value")

    def _sync_predict_impl(self, ctx: Dict[str, Any]) -> MCPModelPrediction:
        """Transform + predict on worker thread (keeps asyncio event loop responsive)."""
        t0 = time.perf_counter()
        df5 = _ctx_dataframe(ctx, "v43_df5m", "df5m")
        df15 = _ctx_dataframe(ctx, "v43_df15m", "df15m")
        df1h = _ctx_dataframe(ctx, "v43_df1h", "df1h")
        df_fund = _ctx_dataframe(ctx, "v43_df_funding", "df_funding")
        if not isinstance(df5, pd.DataFrame):
            raise ValueError("v43 predict requires v43_df5m as pd.DataFrame")
        if not isinstance(df_fund, pd.DataFrame):
            raise ValueError("v43 predict requires v43_df_funding as pd.DataFrame")
        # df15m and df1h are accepted as None — build_v43_feature_matrix resamples HTF
        # from 5m internally and silently discards these arguments.
        if df15 is None:
            df15 = pd.DataFrame()
        if df1h is None:
            df1h = pd.DataFrame()

        transform = getattr(self._fe, "transform", None)
        if not callable(transform):
            raise RuntimeError("feature_engineer missing transform()")

        df_feat = transform(
            df5,
            df15,
            df1h,
            df_fund,
            include_target=False,
        )
        if df_feat is None or len(df_feat) < 2:
            raise ValueError("feature transform returned < 2 rows")

        cols = [c for c in self._feature_names if c in df_feat.columns]
        if len(cols) < len(self._feature_names) * 0.9:
            missing = set(self._feature_names) - set(df_feat.columns)
            logger.warning(
                "v43_feature_columns_partial",
                missing_sample=sorted(missing)[:12],
                found=len(cols),
                expected=len(self._feature_names),
            )

        use_cols = [c for c in self._feature_names if c in df_feat.columns]
        if not use_cols:
            raise ValueError("no model feature columns present after transform")

        X_df = df_feat[use_cols].iloc[[-2]]
        X = X_df.values.astype(np.float64, copy=False)
        closed_row = df_feat.iloc[-2]
        closed_feats: Dict[str, float] = {}
        for k in df_feat.columns:
            try:
                v = closed_row[k]
                if pd.isna(v):
                    continue
                fv = float(v)
                if np.isfinite(fv):
                    closed_feats[str(k)] = fv
            except (TypeError, ValueError):
                continue

        regime = "neutral"
        if "regime_label" in df_feat.columns:
            try:
                regime = str(df_feat["regime_label"].iloc[-2])
            except Exception:
                regime = "neutral"

        floor = float(getattr(settings, "jacksparrow_v43_signal_threshold_floor", 0.005))
        short_enabled = bool(
            getattr(settings, "jacksparrow_v43_short_execution_enabled", False)
        )
        head_payloads: Dict[str, Dict[str, Any]] = {}
        primary_fb = int(self._training_forward_bars)
        primary_proba = 0.0
        primary_thr = floor
        primary_short_thr = floor
        primary_pred_val = 0.0
        primary_conf = 0.0
        primary_unc = 0.05
        primary_u_scale = uncertainty_scale(primary_unc)

        if self._multihead is None:
            raise RuntimeError("multi-head bundle not loaded")

        for hkey in V43_HORIZON_KEYS:
            fb = int(V43_HORIZON_KEY_TO_BARS[hkey])
            head_ens = self._multihead.get_head(fb)
            if head_ens is None:
                continue
            active = get_regime_model(regime, self._regime_models, head_ens)
            thr = get_signal_threshold(regime, head_ens, active, floor=floor)
            short_thr = get_short_signal_threshold(
                regime,
                head_ens,
                active,
                floor=floor,
                long_threshold=thr,
            )
            if active is None:
                proba0 = 0.0
                unc_h = 1.0
            else:
                try:
                    proba_arr = self._predict_active(active, X, X_df)
                except Exception as active_exc:
                    if active is head_ens:
                        raise
                    logger.warning(
                        "v43_head_regime_fallback",
                        horizon=hkey,
                        error=str(active_exc),
                    )
                    proba_arr = self._predict_active(head_ens, X, X_df)
                proba0 = float(proba_arr[0]) if proba_arr.size else 0.0
                unc_h = float(ensemble_predict_uncertainty(head_ens, X_df))
            head_payloads[hkey] = {
                "horizon_key": hkey,
                "forward_bars": fb,
                "horizon_minutes": forward_bars_to_minutes(fb),
                "expected_return": proba0,
                "threshold": thr,
                "short_threshold": short_thr,
                "regime": regime,
                "uncertainty": unc_h,
            }
            if fb == primary_fb:
                primary_proba = proba0
                primary_thr = thr
                primary_short_thr = short_thr
                primary_unc = unc_h
                primary_u_scale = uncertainty_scale(primary_unc)
                edge = float(proba0) - float(thr)
                primary_pred_val = float(np.tanh(edge * 80.0))
                primary_conf = _v43_head_confidence(edge, thr, primary_u_scale)

        reasoning = (
            f"v43 multi-head regime={regime} primary={primary_fb}bars "
            f"er={primary_proba:.5f} thr={primary_thr:.5f}"
        )

        out_ctx: Dict[str, Any] = {
            "format": "jacksparrow_v43_multihead",
            "multi_horizon_heads": head_payloads,
            "expected_return": float(primary_proba),
            "threshold": float(primary_thr),
            "short_threshold": float(primary_short_thr),
            "regime": regime,
            "uncertainty": float(primary_unc),
            "unc_scale": float(primary_u_scale),
            "bar_index_hint": int(closed_5m_bar_index(df5)),
            "feature_names_used": use_cols,
            "RECOMMENDED_LONG_THRESHOLD": float(primary_thr),
            "RECOMMENDED_SHORT_THRESHOLD": float(primary_short_thr),
            "closed_bar_features": closed_feats,
            "primary_execution_horizon_bars": primary_fb,
            "training_forward_bars": primary_fb,
            "target_horizon_bars": primary_fb,
            "short_execution_enabled": short_enabled,
        }

        ms = (time.perf_counter() - t0) * 1000.0
        self._health = "healthy"
        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=primary_pred_val,
            confidence=primary_conf,
            reasoning=reasoning,
            features_used=list(use_cols),
            feature_importance={},
            computation_time_ms=ms,
            health_status="healthy",
            context=out_ctx,
        )

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        await self.initialize()
        await self._reload_if_stale()
        self._call_count += 1
        t0 = time.perf_counter()
        ctx = dict(request.context or {})
        unc = 0.05
        u_scale = uncertainty_scale(unc)
        proba0 = 0.0
        thr = float(getattr(settings, "jacksparrow_v43_signal_threshold_floor", 0.005))
        regime = "neutral"
        try:
            async with self._predict_lock:
                pred = await asyncio.to_thread(self._sync_predict_impl, ctx)
            wall_ms = (time.perf_counter() - t0) * 1000.0
            return pred.model_copy(update={"computation_time_ms": wall_ms})
        except Exception as e:
            self._error_count += 1
            self._health = "degraded"
            logger.error(
                "jacksparrow_v43_predict_failed",
                model_name=self._model_name,
                error=str(e),
                exc_info=True,
            )
            ms = (time.perf_counter() - t0) * 1000.0
            return MCPModelPrediction(
                model_name=self._model_name,
                model_version=self._model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"v43 inference error: {e}",
                features_used=[],
                feature_importance={},
                computation_time_ms=ms,
                health_status="degraded",
                context={
                    "format": "jacksparrow_v43",
                    "error": str(e),
                    "expected_return": float(proba0),
                    "threshold": float(thr),
                    "regime": regime,
                    "uncertainty": float(unc),
                    "unc_scale": float(u_scale),
                },
            )


def _register_v43_build_feature_matrix() -> None:
    try:
        from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix

        _v43_shims.set_v43_build_feature_matrix(build_v43_feature_matrix)
        logger.info("v43_build_feature_matrix_registered")
    except Exception as exc:  # pragma: no cover
        logger.warning("v43_build_feature_matrix_register_failed", error=str(exc))


_register_v43_build_feature_matrix()
