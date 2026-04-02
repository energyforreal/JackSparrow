"""
JackSparrow v4 BTCUSD entry/exit ensemble MCP model node.

This node wraps the v4 artefacts in `agent/model_storage/jacksparrow_v4_BTCUSD`,
which are exported as:

- entry_model_BTCUSD_<tf>.joblib
- entry_scaler_BTCUSD_<tf>.joblib
- exit_model_BTCUSD_<tf>.joblib
- exit_scaler_BTCUSD_<tf>.joblib
- metadata_BTCUSD_<tf>.json

The node:
- Builds a feature vector in the order declared in metadata["features"]
  using the `feature_names` and `features` carried in MCPModelRequest.context.
- Applies the entry and exit scalers (when present).
- Uses the entry classifier to produce a BUY/SELL/HOLD-style signal in [-1, +1].
- Uses the exit classifier to produce an EXIT/HOLD signal in [-1, +1].
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import time

import numpy as np
import structlog

try:  # Prefer joblib for .joblib artefacts, fall back to pickle for compatibility.
    import joblib  # type: ignore

    def _load(path: Path) -> Any:
        return joblib.load(path)
except Exception:  # pragma: no cover - defensive fallback
    import pickle  # type: ignore

    def _load(path: Path) -> Any:
        with open(path, "rb") as f:
            return pickle.load(f)

from agent.core.config import settings
from agent.core.exceptions import FeatureAlignmentError
from agent.models.mcp_model_node import (
    MCPModelNode,
    MCPModelPrediction,
    MCPModelRequest,
)


logger = structlog.get_logger()


@dataclass
class V4Artifacts:
    """Resolved artefact paths for a single timeframe."""

    entry_model_path: Optional[Path]
    entry_scaler_path: Optional[Path]
    entry_long_model_path: Optional[Path]
    entry_long_scaler_path: Optional[Path]
    entry_short_model_path: Optional[Path]
    entry_short_scaler_path: Optional[Path]
    exit_model_path: Optional[Path]
    exit_scaler_path: Optional[Path]
    features_path: Optional[Path]


def _entry_signal(proba: np.ndarray) -> Tuple[float, float]:
    """Map 3-class [SELL, HOLD, BUY] probabilities to [-1, +1] signal and confidence."""
    if proba is None or len(proba) != 3:
        return 0.0, 0.0
    sell, hold, buy = float(proba[0]), float(proba[1]), float(proba[2])
    signal = buy - sell
    # For execution gating we only care about directional conviction.
    # HOLD-dominant models should not inflate confidence.
    confidence = max(sell, buy)
    return signal, confidence


def _exit_signal(proba: np.ndarray) -> Tuple[float, float]:
    """Map 2-class [HOLD, EXIT] probabilities to [-1, +1] exit signal and confidence."""
    if proba is None or len(proba) != 2:
        return 0.0, 0.0
    hold, exit_ = float(proba[0]), float(proba[1])
    signal = exit_ - hold
    confidence = max(hold, exit_)
    return signal, confidence


class V4EnsembleNode(MCPModelNode):
    """MCP Model Node for v4 BTCUSD entry/exit models."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        timeframe: str,
        features: List[str],
        artifacts: V4Artifacts,
        metadata: Dict[str, Any],
    ) -> None:
        self._model_name = model_name
        self._model_version = model_version
        self._timeframe = timeframe
        self._feature_names = features
        self._metadata = metadata

        # Lazy-loaded artefacts
        self._artifacts = artifacts
        self._entry_model: Optional[Any] = None
        self._entry_long_model: Optional[Any] = None
        self._entry_short_model: Optional[Any] = None
        self._exit_model: Optional[Any] = None
        self._entry_scaler: Optional[Any] = None
        self._entry_long_scaler: Optional[Any] = None
        self._entry_short_scaler: Optional[Any] = None
        self._exit_scaler: Optional[Any] = None

        # Health metrics
        self._health_status = "healthy"
        self._call_count = 0
        self._total_ms = 0.0
        self._error_count = 0
        self._training_stats: Dict[str, Dict[str, float]] = {}
        self._drift_stats_loaded = False

    def _load_feature_drift_stats(self) -> None:
        if self._drift_stats_loaded:
            return
        self._drift_stats_loaded = True
        try:
            from feature_store.drift import load_training_stats

            base_dir: Optional[Path] = None
            meta_path = self._metadata.get("_metadata_path")
            if isinstance(meta_path, str) and meta_path:
                try:
                    base_dir = Path(meta_path).parent
                except Exception:
                    base_dir = None

            if base_dir is None and self._artifacts.features_path is not None:
                base_dir = self._artifacts.features_path.parent
            if base_dir is None:
                return

            candidates = [
                base_dir / "feature_schema.json",
                base_dir / "training_metadata.json",
                base_dir / "feature_drift_stats.json",
            ]
            for p in candidates:
                stats = load_training_stats(p)
                if stats:
                    self._training_stats = stats
                    logger.info(
                        "feature_drift_stats_loaded",
                        model_name=self.model_name,
                        timeframe=self._timeframe,
                        path=str(p),
                        feature_count=len(stats),
                    )
                    return
        except Exception as e:
            logger.debug(
                "feature_drift_stats_load_skipped",
                model_name=self.model_name,
                timeframe=self._timeframe,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_metadata(cls, metadata_path: Path) -> "V4EnsembleNode":
        """Create node from v4 metadata JSON."""
        base_dir = metadata_path.parent
        with metadata_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        model_name = meta.get("model_name", metadata_path.stem)
        version = meta.get("version", "4.0.0")
        timeframe = meta.get("timeframe", "unknown")
        features: List[str] = meta.get("features", [])

        artifacts_cfg = meta.get("artifacts", {})

        def _opt(name: str) -> Optional[Path]:
            rel = artifacts_cfg.get(name)
            return (base_dir / rel) if rel else None

        entry_model_rel = artifacts_cfg.get("entry_model")
        entry_long_rel = artifacts_cfg.get("entry_long_model")
        entry_short_rel = artifacts_cfg.get("entry_short_model")
        exit_model_rel = artifacts_cfg.get("exit_model")
        artifacts = V4Artifacts(
            entry_model_path=(base_dir / entry_model_rel) if entry_model_rel else None,
            entry_scaler_path=_opt("entry_scaler"),
            entry_long_model_path=(base_dir / entry_long_rel) if entry_long_rel else None,
            entry_long_scaler_path=_opt("entry_long_scaler"),
            entry_short_model_path=(base_dir / entry_short_rel) if entry_short_rel else None,
            entry_short_scaler_path=_opt("entry_short_scaler"),
            exit_model_path=(base_dir / exit_model_rel) if exit_model_rel else None,
            exit_scaler_path=_opt("exit_scaler"),
            features_path=_opt("features"),
        )

        # Stash metadata path for optional drift-stats autodiscovery.
        meta["_metadata_path"] = str(metadata_path)

        return cls(
            model_name=model_name,
            model_version=version,
            timeframe=timeframe,
            features=features,
            artifacts=artifacts,
            metadata=meta,
        )

    # ------------------------------------------------------------------
    # MCPModelNode interface
    # ------------------------------------------------------------------
    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return "v4_entry_exit_ensemble"

    async def initialize(self) -> None:
        """Lazy-load models and scalers on first use."""
        self._load_feature_drift_stats()
        if self._artifacts.entry_model_path and self._entry_model is None:
            self._entry_model = _load(self._artifacts.entry_model_path)
        if self._artifacts.entry_long_model_path and self._entry_long_model is None:
            self._entry_long_model = _load(self._artifacts.entry_long_model_path)
        if self._artifacts.entry_short_model_path and self._entry_short_model is None:
            self._entry_short_model = _load(self._artifacts.entry_short_model_path)
        if self._artifacts.exit_model_path and self._exit_model is None:
            self._exit_model = _load(self._artifacts.exit_model_path)
        if self._artifacts.entry_scaler_path and self._entry_scaler is None:
            try:
                self._entry_scaler = _load(self._artifacts.entry_scaler_path)
            except Exception:
                self._entry_scaler = None
        if self._artifacts.entry_long_scaler_path and self._entry_long_scaler is None:
            try:
                self._entry_long_scaler = _load(self._artifacts.entry_long_scaler_path)
            except Exception:
                self._entry_long_scaler = None
        if self._artifacts.entry_short_scaler_path and self._entry_short_scaler is None:
            try:
                self._entry_short_scaler = _load(self._artifacts.entry_short_scaler_path)
            except Exception:
                self._entry_short_scaler = None
        if self._artifacts.exit_scaler_path and self._exit_scaler is None:
            try:
                self._exit_scaler = _load(self._artifacts.exit_scaler_path)
            except Exception:
                self._exit_scaler = None

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        # Ensure models are loaded
        await self.initialize()

        t0 = time.perf_counter()
        self._call_count += 1
        try:
            features_vec, applied_feature_names = self._build_feature_vector(request)

            if not features_vec:
                raise ValueError("No features available for v4 ensemble prediction.")

            # Optional drift monitoring against training baselines (when available).
            drifted_features: List[str] = []
            if (
                bool(getattr(settings, "feature_drift_logging_enabled", True))
                and self._training_stats
                and applied_feature_names
            ):
                try:
                    from feature_store.drift import check_drift

                    sigma = float(getattr(settings, "feature_drift_sigma_threshold", 4.0) or 4.0)
                    drifted_features = check_drift(
                        feature_vector=[float(x) for x in features_vec],
                        feature_names=list(applied_feature_names),
                        training_stats=self._training_stats,
                        threshold_sigma=sigma,
                    )
                    if drifted_features:
                        logger.warning(
                            "feature_drift_detected",
                            model_name=self.model_name,
                            timeframe=self._timeframe,
                            drifted_count=len(drifted_features),
                            sigma_threshold=sigma,
                            drifted_features=drifted_features[:25],
                        )
                except Exception as e:
                    logger.debug(
                        "feature_drift_check_failed",
                        model_name=self.model_name,
                        timeframe=self._timeframe,
                        error=str(e),
                    )

            X_entry = np.array([features_vec], dtype=np.float32)
            X_exit = np.array([features_vec], dtype=np.float32)
            use_ml_exit = getattr(settings, "use_ml_exit_model", False)
            if use_ml_exit and self._exit_scaler is not None:
                X_exit = self._exit_scaler.transform(X_exit)
            # Entry probabilities:
            # - New contract: binary long/short entry models
            # - Legacy contract: single 3-class [SELL, HOLD, BUY] entry model
            if self._entry_long_model is not None and self._entry_short_model is not None:
                X_entry_long = np.array([features_vec], dtype=np.float32)
                X_entry_short = np.array([features_vec], dtype=np.float32)
                if self._entry_long_scaler is not None:
                    X_entry_long = self._entry_long_scaler.transform(X_entry_long)
                if self._entry_short_scaler is not None:
                    X_entry_short = self._entry_short_scaler.transform(X_entry_short)
                long_proba = self._entry_long_model.predict_proba(X_entry_long)[0]  # type: ignore[attr-defined]
                short_proba = self._entry_short_model.predict_proba(X_entry_short)[0]  # type: ignore[attr-defined]
                if long_proba is None or short_proba is None or len(long_proba) < 2 or len(short_proba) < 2:
                    raise ValueError("binary entry models returned invalid probabilities")
                buy = float(long_proba[1])
                sell = float(short_proba[1])
                hold = float(max(0.0, 1.0 - max(buy, sell)))
                entry_proba_raw = np.array([sell, hold, buy], dtype=np.float32)
            else:
                if self._entry_model is None:
                    raise ValueError(
                        f"v4 ensemble {self._timeframe}: no entry model artifacts loaded "
                        f"(expected entry_long+entry_short or legacy entry_model)"
                    )
                if self._entry_scaler is not None:
                    X_entry = self._entry_scaler.transform(X_entry)
                entry_proba_raw = self._entry_model.predict_proba(X_entry)[0]  # type: ignore[attr-defined]
                if entry_proba_raw is None:
                    t_ms = (time.perf_counter() - t0) * 1000.0
                    self._total_ms += t_ms
                    warning = f"v4 ensemble {self._timeframe}: entry model returned None probabilities"
                    logger.warning(
                        "v4_entry_proba_unexpected_shape",
                        model_name=self.model_name,
                        timeframe=self._timeframe,
                        proba_len=0,
                        error=warning,
                    )
                    self._health_status = "degraded"
                    return MCPModelPrediction(
                        model_name=self.model_name,
                        model_version=self.model_version,
                        prediction=0.0,
                        confidence=0.0,
                        reasoning=warning,
                        features_used=applied_feature_names,
                        feature_importance={},
                        computation_time_ms=round(t_ms, 2),
                        health_status="degraded",
                    )
                entry_len = len(entry_proba_raw)
                if entry_len == 2:
                    sell = float(entry_proba_raw[0])
                    buy = float(entry_proba_raw[1])
                    entry_proba_raw = np.array([sell, 0.0, buy], dtype=np.float32)
                elif entry_len != 3:
                    raise ValueError(
                        f"v4 ensemble {self._timeframe}: entry model returned {entry_len} classes (expected 2/3)"
                    )

            # Exit: optional ML classifier (often miscalibrated); default off — use TP/SL/trailing/time in execution
            if use_ml_exit and self._exit_model is not None:
                exit_proba_raw = self._exit_model.predict_proba(X_exit)[0]  # type: ignore[attr-defined]
                if exit_proba_raw is None or len(exit_proba_raw) < 2:
                    t_ms = (time.perf_counter() - t0) * 1000.0
                    self._total_ms += t_ms
                    warning = (
                        f"v4 ensemble {self._timeframe}: exit model returned "
                        f"{0 if exit_proba_raw is None else len(exit_proba_raw)} classes (expected 2)"
                    )
                    logger.warning(
                        "v4_exit_proba_unexpected_shape",
                        model_name=self.model_name,
                        timeframe=self._timeframe,
                        proba_len=0 if exit_proba_raw is None else len(exit_proba_raw),
                    )
                    self._health_status = "degraded"
                    return MCPModelPrediction(
                        model_name=self.model_name,
                        model_version=self.model_version,
                        prediction=0.0,
                        confidence=0.0,
                        reasoning=warning,
                        features_used=applied_feature_names,
                        feature_importance={},
                        computation_time_ms=round(t_ms, 2),
                        health_status="degraded",
                    )
                exit_signal, exit_conf = _exit_signal(exit_proba_raw)
                exit_hold = float(exit_proba_raw[0])
                exit_exit = float(exit_proba_raw[1])
            else:
                exit_proba_raw = np.array([1.0, 0.0], dtype=np.float32)
                exit_signal, exit_conf = 0.0, 1.0
                exit_hold, exit_exit = 1.0, 0.0

            entry_signal, entry_conf = _entry_signal(entry_proba_raw)
            if (
                self._entry_long_model is not None
                and self._entry_short_model is not None
            ):
                gap = float(getattr(settings, "entry_long_short_min_gap", 0.0) or 0.0)
                if gap > 0:
                    buy_ls = float(entry_proba_raw[2])
                    sell_ls = float(entry_proba_raw[0])
                    if abs(buy_ls - sell_ls) < gap:
                        entry_signal = 0.0
                        entry_conf = min(buy_ls, sell_ls)

            reasoning = (
                f"v4 ensemble {self._timeframe}: "
                f"entry_signal={entry_signal:+.3f} (conf={entry_conf:.2f}), "
                f"exit_signal={exit_signal:+.3f} (conf={exit_conf:.2f})"
                + (
                    " [ML exit disabled; use execution TP/SL/trailing]"
                    if not use_ml_exit
                    else ""
                )
            )

            t_ms = (time.perf_counter() - t0) * 1000.0
            self._total_ms += t_ms

            # Recover model health after successful inference.
            if self._health_status != "healthy":
                self._health_status = "healthy"
                if self._error_count > 0:
                    self._error_count -= 1

            context: Dict[str, Any] = {
                "timeframe": self._timeframe,
                "entry_proba": {
                    "sell": float(entry_proba_raw[0]),
                    "hold": float(entry_proba_raw[1]),
                    "buy": float(entry_proba_raw[2]),
                },
                "exit_proba": {
                    "hold": exit_hold,
                    "exit": exit_exit,
                },
                "entry_signal": entry_signal,
                "entry_confidence": entry_conf,
                "exit_signal": exit_signal,
                "exit_confidence": exit_conf,
                "feature_names_used": applied_feature_names,
                "drifted_features": drifted_features,
                "runtime_threshold_hints": self._metadata.get("runtime_threshold_hints", {}),
                "RECOMMENDED_LONG_THRESHOLD": self._metadata.get(
                    "RECOMMENDED_LONG_THRESHOLD"
                ),
                "RECOMMENDED_SHORT_THRESHOLD": self._metadata.get(
                    "RECOMMENDED_SHORT_THRESHOLD"
                ),
            }

            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=entry_signal,
                confidence=entry_conf,
                reasoning=reasoning,
                features_used=applied_feature_names,
                feature_importance={},  # v4 artefacts do not currently export per-feature importance
                computation_time_ms=round(t_ms, 2),
                health_status=self._health_status,
                context=context,
            )
        except Exception as exc:  # pragma: no cover - defensive error path
            self._error_count += 1
            # Mark node as degraded after repeated failures but keep contributing
            # low-confidence predictions so the registry can still form a consensus
            # instead of hard-failing the entire request.
            if self._error_count >= 5:
                self._health_status = "degraded"
            logger.error(
                "v4_ensemble_inference_failed",
                model_name=self.model_name,
                timeframe=self._timeframe,
                error=str(exc),
                feature_count=len(getattr(request, "features", []) or []),
                expected_feature_count=len(self._feature_names),
                context_keys=list((request.context or {}).keys()),
                exc_info=True,
            )
            t_ms = (time.perf_counter() - t0) * 1000.0
            self._total_ms += t_ms

            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"v4 ensemble inference failed: {exc}",
                features_used=[],
                feature_importance={},
                computation_time_ms=round(t_ms, 2),
                health_status="degraded",
            )

    async def get_health_status(self) -> Dict[str, Any]:
        avg_ms = (self._total_ms / self._call_count) if self._call_count else 0.0
        return {
            "status": self._health_status,
            "model_name": self.model_name,
            "version": self.model_version,
            "timeframe": self._timeframe,
            "call_count": self._call_count,
            "error_count": self._error_count,
            "avg_inference_ms": round(avg_ms, 2),
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "timeframe": self._timeframe,
            "features_required": self._feature_names,
            "feature_count": len(self._feature_names),
            "output": {
                "prediction": "entry signal [-1, +1]",
                "context.entry_signal": "entry signal [-1, +1]",
                "context.exit_signal": "exit signal [-1, +1]",
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_feature_vector(
        self, request: MCPModelRequest
    ) -> Tuple[List[float], List[str]]:
        """Align incoming feature vector with v4 feature ordering.

        Prefer mapping by context['feature_names']; if unavailable or incomplete,
        fall back to slicing the leading n features.
        """
        raw_features = list(request.features)
        ctx = request.context or {}
        incoming_names: List[str] = ctx.get("feature_names") or []

        if incoming_names and len(incoming_names) == len(raw_features):
            index = {name: i for i, name in enumerate(incoming_names)}
            aligned: List[float] = []
            applied_names: List[str] = []
            for name in self._feature_names:
                if name in index:
                    aligned.append(raw_features[index[name]])
                    applied_names.append(name)
            if len(aligned) == len(self._feature_names):
                return aligned, applied_names

        # Hard-fail: refuse positional fallback to avoid silent semantic mismatch
        logger.error(
            "v4_feature_alignment_failed",
            model_name=self._model_name,
            expected_features=self._feature_names,
            incoming_names=incoming_names[:20] if incoming_names else [],
            expected_count=len(self._feature_names),
            incoming_count=len(incoming_names) if incoming_names else 0,
            raw_feature_count=len(raw_features),
        )
        raise FeatureAlignmentError(
            f"feature_names missing or incomplete in context for {self._model_name}. "
            f"Expected {len(self._feature_names)} features by name, "
            f"got {len(incoming_names) if incoming_names else 0} incoming names. "
            "Refusing positional fallback to avoid silent semantic mismatch."
        )

