"""
Single consolidated BTCUSD model MCP node.

Loads one metadata-driven artifact that consumes unified multi-timeframe features
and emits one directional output for runtime decisioning.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import time

import numpy as np
import structlog

try:
    import joblib  # type: ignore

    def _load(path: Path) -> Any:
        return joblib.load(path)
except Exception:  # pragma: no cover
    import pickle  # type: ignore

    def _load(path: Path) -> Any:
        with open(path, "rb") as f:
            return pickle.load(f)

from agent.core.exceptions import FeatureAlignmentError
from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest

logger = structlog.get_logger()


@dataclass
class ConsolidatedArtifacts:
    model_path: Path
    scaler_path: Optional[Path]


class ConsolidatedModelNode(MCPModelNode):
    """MCP node wrapping a single consolidated classifier/regressor artifact."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        features: List[str],
        artifacts: ConsolidatedArtifacts,
        metadata: Dict[str, Any],
    ) -> None:
        self._model_name = model_name
        self._model_version = model_version
        self._feature_names = features
        self._artifacts = artifacts
        self._metadata = metadata

        self._model: Optional[Any] = None
        self._scaler: Optional[Any] = None
        self._health_status = "healthy"
        self._call_count = 0
        self._total_ms = 0.0
        self._error_count = 0

    @classmethod
    def from_metadata(cls, metadata_path: Path) -> "ConsolidatedModelNode":
        """Build consolidated model node from metadata JSON."""
        base_dir = metadata_path.parent
        with metadata_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        artifacts_cfg = meta.get("artifacts", {}) if isinstance(meta, dict) else {}
        model_rel = artifacts_cfg.get("model")
        if not model_rel:
            raise ValueError(
                f"Consolidated metadata missing artifacts.model: {metadata_path}"
            )
        scaler_rel = artifacts_cfg.get("scaler")

        node = cls(
            model_name=str(meta.get("model_name", "jacksparrow_BTCUSD_consolidated")),
            model_version=str(meta.get("version", "1.0.0")),
            features=list(meta.get("features", [])),
            artifacts=ConsolidatedArtifacts(
                model_path=base_dir / model_rel,
                scaler_path=(base_dir / scaler_rel) if scaler_rel else None,
            ),
            metadata=meta,
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
        return "single_consolidated_entry"

    async def initialize(self) -> None:
        if self._model is None:
            self._model = _load(self._artifacts.model_path)
        if self._artifacts.scaler_path is not None and self._scaler is None:
            try:
                self._scaler = _load(self._artifacts.scaler_path)
            except Exception:
                self._scaler = None

    def _build_feature_vector(
        self, request: MCPModelRequest
    ) -> Tuple[List[float], List[str]]:
        raw_features = list(request.features)
        ctx = request.context or {}
        incoming_names: List[str] = ctx.get("feature_names") or []

        if incoming_names and len(incoming_names) == len(raw_features):
            index = {name: i for i, name in enumerate(incoming_names)}
            aligned: List[float] = []
            used: List[str] = []
            for name in self._feature_names:
                if name in index:
                    aligned.append(float(raw_features[index[name]]))
                    used.append(name)
            if len(aligned) == len(self._feature_names):
                return aligned, used

        logger.error(
            "consolidated_feature_alignment_failed",
            model_name=self._model_name,
            expected_count=len(self._feature_names),
            incoming_count=len(incoming_names),
            raw_feature_count=len(raw_features),
        )
        raise FeatureAlignmentError(
            f"feature_names missing/incomplete for {self._model_name}. "
            f"Expected {len(self._feature_names)}, got {len(incoming_names)}."
        )

    def _prediction_to_proba(self, X: np.ndarray) -> Tuple[np.ndarray, float, float]:
        assert self._model is not None
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba(X)[0]  # type: ignore[attr-defined]
            if proba is None:
                raise ValueError("predict_proba returned None")
            if len(proba) == 3:
                sell, hold, buy = float(proba[0]), float(proba[1]), float(proba[2])
            elif len(proba) == 2:
                sell, buy = float(proba[0]), float(proba[1])
                hold = float(max(0.0, 1.0 - max(sell, buy)))
            else:
                raise ValueError(f"Unsupported class count from predict_proba: {len(proba)}")
        else:
            pred = float(self._model.predict(X)[0])  # type: ignore[attr-defined]
            pred = max(-1.0, min(1.0, pred))
            buy = max(0.0, pred)
            sell = max(0.0, -pred)
            hold = max(0.0, 1.0 - max(buy, sell))
        signal = float(buy - sell)
        confidence = float(max(buy, sell))
        return np.array([sell, hold, buy], dtype=np.float32), signal, confidence

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        await self.initialize()
        self._call_count += 1
        t0 = time.perf_counter()
        try:
            features_vec, feature_names = self._build_feature_vector(request)
            X = np.array([features_vec], dtype=np.float32)
            if self._scaler is not None:
                X = self._scaler.transform(X)
            entry_proba, signal, confidence = self._prediction_to_proba(X)
            t_ms = (time.perf_counter() - t0) * 1000.0
            self._total_ms += t_ms
            self._health_status = "healthy"
            if self._error_count > 0:
                self._error_count -= 1

            context: Dict[str, Any] = {
                "mode": "single_consolidated",
                "entry_proba": {
                    "sell": float(entry_proba[0]),
                    "hold": float(entry_proba[1]),
                    "buy": float(entry_proba[2]),
                },
                "entry_signal": signal,
                "entry_confidence": confidence,
                "feature_names_used": feature_names,
                "runtime_threshold_hints": self._metadata.get("runtime_threshold_hints", {}),
                "RECOMMENDED_LONG_THRESHOLD": self._metadata.get("RECOMMENDED_LONG_THRESHOLD"),
                "RECOMMENDED_SHORT_THRESHOLD": self._metadata.get("RECOMMENDED_SHORT_THRESHOLD"),
            }

            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=signal,
                confidence=confidence,
                reasoning=(
                    "single consolidated model: "
                    f"entry_signal={signal:+.3f} conf={confidence:.2f}"
                ),
                features_used=feature_names,
                feature_importance={},
                computation_time_ms=round(t_ms, 2),
                health_status=self._health_status,
                context=context,
            )
        except Exception as exc:
            self._error_count += 1
            if self._error_count >= 5:
                self._health_status = "degraded"
            t_ms = (time.perf_counter() - t0) * 1000.0
            self._total_ms += t_ms
            logger.error(
                "consolidated_model_inference_failed",
                model_name=self.model_name,
                error=str(exc),
                exc_info=True,
            )
            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"consolidated model inference failed: {exc}",
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
            "model_loaded": self._model is not None,
            "call_count": self._call_count,
            "error_count": self._error_count,
            "avg_inference_ms": round(avg_ms, 2),
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "features_required": self._feature_names,
            "feature_count": len(self._feature_names),
            "single_model_mode": True,
            "output": {
                "prediction": "entry signal [-1, +1]",
                "context.entry_proba": "sell/hold/buy probabilities",
            },
        }
