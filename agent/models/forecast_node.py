"""Joblib node for the 30-minute forecast bundle."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import structlog

from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from research.forecast_30m.contract_v5 import (
    FORECAST_BUNDLE_DIR_NAME,
    FORECAST_DECISION_PATH,
    LABEL_VERSION,
)
from research.forecast_30m.inference import load_artifact, predict_latest

logger = structlog.get_logger()


def _ctx_df(ctx: Dict[str, Any], *keys: str) -> Optional[pd.DataFrame]:
    for key in keys:
        value = ctx.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return value
    return None


def closed_ohlcv_for_forecast(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize an agent 30-minute frame to the research OHLCV schema."""
    out = frame.copy()
    if "time" not in out.columns:
        if "timestamp" not in out.columns:
            raise ValueError("forecast frame needs time or timestamp")
        out["time"] = pd.to_datetime(out["timestamp"], utc=True)
    else:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in out.columns]
    if missing:
        raise ValueError(f"forecast frame is missing columns: {missing}")
    return out.sort_values("time").reset_index(drop=True)


class ForecastModelNode(MCPModelNode):
    """Loads a promoted v5 joblib bundle and forecasts the last closed 30m bar."""

    def __init__(self, bundle_dir: Path, artifact: dict[str, Any]) -> None:
        self._bundle_dir = bundle_dir
        self._artifact = artifact
        manifest = dict(artifact.get("manifest") or {})
        self._manifest = manifest
        self._model_name = str(
            manifest.get("model_name") or "jacksparrow_forecast_BTCUSD_30m"
        )
        self._model_version = str(manifest.get("label_version") or LABEL_VERSION)
        self._initialized = False
        self._health = "unknown"
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
        return "forecast_30m_xgb"

    @property
    def resolution(self) -> str:
        return "30m"

    @classmethod
    def from_bundle_dir(cls, bundle_dir: Path) -> "ForecastModelNode":
        """Load ``manifest.json`` and ``models.joblib``. Refuse unapproved bundles.

        Args:
            bundle_dir: Directory produced by a passing v5 promotion.

        Returns:
            An uninitialized node.

        Raises:
            FileNotFoundError: If the artifact files are missing.
            RuntimeError: If ``orders_enabled`` is false.
        """
        manifest_path = bundle_dir / "manifest.json"
        models_path = bundle_dir / "models.joblib"
        if not manifest_path.is_file() or not models_path.is_file():
            raise FileNotFoundError(f"forecast artifact not found: {bundle_dir}")
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not bool(manifest.get("orders_enabled")):
            raise RuntimeError("forecast bundle is not approved for live orders")
        artifact = load_artifact(bundle_dir)
        return cls(bundle_dir, artifact)

    async def initialize(self) -> None:
        """Mark the loaded artifact ready for inference."""
        if "direction" not in (self._artifact.get("models") or {}):
            raise RuntimeError("forecast bundle has no direction model")
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "forecast_node_initialized",
            model_name=self._model_name,
            bundle=str(self._bundle_dir),
            spec_version=self._manifest.get("spec_version"),
        )

    def _sync_predict_impl(self, ctx: Dict[str, Any]) -> MCPModelPrediction:
        t0 = time.perf_counter()
        if not self._initialized:
            raise RuntimeError("ForecastModelNode is not initialized")
        frame = _ctx_df(ctx, "v43_df30m", "df30m", "df_30m")
        if frame is None:
            raise ValueError("Forecast predict requires v43_df30m")
        ohlcv = closed_ohlcv_for_forecast(frame)
        forecast = predict_latest(self._artifact, ohlcv)
        elapsed = (time.perf_counter() - t0) * 1000.0
        signal = str(forecast.get("signal") or "HOLD")
        probability = float(forecast.get("direction_probability") or 0.0)
        if signal == "BUY":
            score = probability
        elif signal == "SELL":
            score = -probability
        else:
            score = 0.0
        context = {
            "tf_key": "30m",
            "resolution": "30m",
            "decision_path": FORECAST_DECISION_PATH,
            "direction": forecast.get("direction"),
            "direction_probability": probability,
            "direction_proba": forecast.get("direction_proba"),
            "probability_floor": forecast.get("probability_floor"),
            "signal": signal,
            "orders_enabled": bool(forecast.get("orders_enabled")),
            "bundle_dir": str(self._bundle_dir),
        }
        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=float(score),
            confidence=probability if signal in {"BUY", "SELL"} else 0.0,
            reasoning="forecast_30m direction",
            features_used=list(self._manifest.get("feature_columns") or []),
            feature_importance={},
            computation_time_ms=float(elapsed),
            health_status=self._health,
            context=context,
        )

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        self._call_count += 1
        try:
            import asyncio

            pred = await asyncio.to_thread(self._sync_predict_impl, request.context or {})
            self._health = "healthy"
            return pred
        except Exception as exc:
            self._error_count += 1
            self._health = "degraded"
            logger.error("forecast_predict_failed", error=str(exc), exc_info=True)
            raise

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "model_version": self._model_version,
            "model_type": self.model_type,
            "resolution": self.resolution,
            "bundle_dir": str(self._bundle_dir),
            "spec_version": self._manifest.get("spec_version"),
            "orders_enabled": bool(self._manifest.get("orders_enabled")),
            "family": FORECAST_BUNDLE_DIR_NAME,
        }

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "health_status": self._health,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
        }
