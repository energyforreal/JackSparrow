"""
JackSparrow v15: single sklearn/XGBoost pipeline per timeframe (v14 artefacts).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

try:
    import joblib
except ImportError:  # pragma: no cover
    joblib = None  # type: ignore

from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest

logger = structlog.get_logger()


def _load_pipeline(path: Path) -> Any:
    if joblib is None:
        raise RuntimeError("joblib is required to load v15 pipeline pickles")
    return joblib.load(path)


def _unwrap_sklearn_estimator(loaded: Any) -> Any:
    """Colab export may be a raw sklearn Pipeline or a dict with a ``model`` key."""
    if isinstance(loaded, dict) and "model" in loaded:
        return loaded["model"]
    return loaded


class PipelineV15Node(MCPModelNode):
    """Full pipeline node: preprocess + XGBClassifier, 3-class [SELL, HOLD, BUY]."""

    def __init__(self, metadata_path: Path, parsed_meta: Dict[str, Any]) -> None:
        self._metadata_path = metadata_path
        self._meta = parsed_meta
        self._model_name = str(parsed_meta["model_name"])
        self._model_version = str(parsed_meta.get("model_version", "v14"))
        self._timeframe = str(parsed_meta.get("timeframe", "15m"))
        self._feature_names: List[str] = list(parsed_meta.get("features") or [])
        self._train_median: Dict[str, float] = dict(parsed_meta.get("train_median") or {})
        pip_name = f"pipeline_{self._timeframe}_v14.pkl"
        self._pipeline_path = metadata_path.parent / pip_name
        self._pipeline: Optional[Any] = None
        self._health = "loading"
        self._call_count = 0
        self._error_count = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return "xgboost_pipeline_v15"

    @property
    def timeframe(self) -> str:
        return self._timeframe

    @classmethod
    def from_metadata_path(cls, metadata_path: Path) -> "PipelineV15Node":
        with metadata_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        raw["_metadata_path"] = str(metadata_path)
        return cls(metadata_path=metadata_path, parsed_meta=raw)

    async def initialize(self) -> None:
        if self._pipeline is not None:
            return
        if not self._pipeline_path.exists():
            self._health = "failed"
            raise FileNotFoundError(f"v15 pipeline missing: {self._pipeline_path}")
        loaded = _load_pipeline(self._pipeline_path)
        self._pipeline = _unwrap_sklearn_estimator(loaded)
        # Smoke test
        row = np.zeros((1, len(self._feature_names)), dtype=np.float64)
        _ = self._pipeline.predict_proba(row)
        self._health = "healthy"
        logger.info(
            "v15_pipeline_loaded",
            model_name=self._model_name,
            path=str(self._pipeline_path),
            n_features=len(self._feature_names),
        )

    def _build_matrix(self, request: MCPModelRequest) -> pd.DataFrame:
        raw = list(request.features)
        ctx = request.context or {}
        incoming_names: List[str] = ctx.get("feature_names") or []
        if incoming_names and len(incoming_names) == len(raw):
            idx = {n: i for i, n in enumerate(incoming_names)}
            row: Dict[str, float] = {}
            for name in self._feature_names:
                if name not in idx:
                    row[name] = float(self._train_median.get(name, 0.0))
                    continue
                v = raw[idx[name]]
                if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                    v = float(self._train_median.get(name, 0.0))
                row[name] = float(v)
        else:
            if len(raw) != len(self._feature_names):
                raise ValueError(
                    f"{self._model_name}: expected {len(self._feature_names)} features, "
                    f"got {len(raw)} (names len={len(incoming_names)})"
                )
            row = {}
            for i, name in enumerate(self._feature_names):
                v = raw[i]
                if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                    v = float(self._train_median.get(name, 0.0))
                row[name] = float(v)
        return pd.DataFrame([row], columns=self._feature_names)

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        await self.initialize()
        t0 = time.perf_counter()
        self._call_count += 1
        if self._pipeline is None or self._health == "failed":
            raise RuntimeError(f"{self._model_name} pipeline not loaded")

        try:
            X = self._build_matrix(request)
            proba = self._pipeline.predict_proba(X)[0]
            p_sell, p_hold, p_buy = float(proba[0]), float(proba[1]), float(proba[2])
            edge = p_buy - p_sell
            confidence = max(p_sell, p_buy)
            t_ms = (time.perf_counter() - t0) * 1000.0
            reasoning = (
                f"v15 {self._timeframe} edge={edge:+.4f} p_buy={p_buy:.3f} "
                f"p_sell={p_sell:.3f} p_hold={p_hold:.3f}"
            )
            ctx = {
                "timeframe": self._timeframe,
                "format": "v15_pipeline",
                "entry_signal": edge,
                "entry_confidence": confidence,
                "entry_proba": {"sell": p_sell, "hold": p_hold, "buy": p_buy},
                "p_buy": p_buy,
                "p_sell": p_sell,
                "p_hold": p_hold,
                "edge": edge,
            }
            return MCPModelPrediction(
                model_name=self._model_name,
                model_version=self._model_version,
                prediction=edge,
                confidence=confidence,
                reasoning=reasoning,
                features_used=list(self._feature_names),
                feature_importance={},
                computation_time_ms=round(t_ms, 2),
                health_status=self._health,
                context=ctx,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._error_count += 1
            if self._error_count >= 5:
                self._health = "degraded"
            t_ms = (time.perf_counter() - t0) * 1000.0
            logger.error(
                "v15_pipeline_predict_failed",
                model_name=self._model_name,
                error=str(exc),
                exc_info=True,
            )
            return MCPModelPrediction(
                model_name=self._model_name,
                model_version=self._model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"v15 inference failed: {exc}",
                features_used=[],
                feature_importance={},
                computation_time_ms=round(t_ms, 2),
                health_status="degraded",
                context={"timeframe": self._timeframe, "format": "v15_pipeline"},
            )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "model_version": self._model_version,
            "model_type": self.model_type,
            "timeframe": self._timeframe,
            "features_required": self._feature_names,
            "feature_count": len(self._feature_names),
            "backtest": self._meta.get("backtest", {}),
            "output": {"prediction": "edge p_buy - p_sell"},
        }

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health,
            "model_name": self._model_name,
            "version": self._model_version,
            "timeframe": self._timeframe,
            "call_count": self._call_count,
            "error_count": self._error_count,
        }


def metadata_is_v15_pipeline(meta_path: Path, raw: Dict[str, Any]) -> bool:
    """True if this JSON is a v14/v15 full-pipeline bundle (not v4 entry/exit)."""
    arts = raw.get("artifacts") or {}
    if arts.get("entry_model") or arts.get("entry_long_model") or arts.get("entry_short_model"):
        return False
    if raw.get("training", {}).get("model_type") != "XGBClassifier":
        return False
    tf = raw.get("timeframe")
    if not tf:
        return False
    pip = meta_path.parent / f"pipeline_{tf}_v14.pkl"
    return pip.is_file()
