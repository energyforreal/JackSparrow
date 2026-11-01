"""Recognition node for the Colab 15-minute checkpoint.

The node reports geometric families and market state. The forecast bundle
remains the order source.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import structlog

from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from research.recognition_15m.contract import (
    ENGINEERED_CHANNELS,
    RECOGNITION_DECISION_PATH,
    SPEC_VERSION,
)
from research.recognition_15m.inference import (
    load_recognition_checkpoint,
    load_recognition_manifest,
    predict_latest,
    recognition_checkpoint_path,
)

logger = structlog.get_logger()


def _frame_from_context(ctx: Dict[str, Any]) -> pd.DataFrame | None:
    """Return the 5-minute frame the recognition window is built from."""
    for key in ("v43_df5m", "df5m", "df_5m"):
        value = ctx.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return value
    return None


class RecognitionModelNode(MCPModelNode):
    """Runs the trained causal TCN on the latest completed 15-minute window."""

    contributes_to_consensus = False

    def __init__(self, checkpoint: Path, artifact: dict[str, Any], manifest: dict[str, Any]) -> None:
        self._checkpoint = checkpoint
        self._artifact = artifact
        self._manifest = manifest
        self._model_name = str(
            manifest.get("model_name") or "jacksparrow_recognition_BTCUSD_15m"
        )
        self._model_version = str(manifest.get("spec_version") or SPEC_VERSION)
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
        return "recognition_15m_tcn"

    @property
    def resolution(self) -> str:
        return "15m"

    @classmethod
    def from_model_dir(cls, model_dir: Path) -> "RecognitionModelNode":
        """Load the checkpoint stored for the agent, or the Colab export.

        Args:
            model_dir: ``MODEL_DIR``.

        Returns:
            An uninitialized node.

        Raises:
            FileNotFoundError: If no recognition checkpoint is on disk.
        """
        checkpoint = recognition_checkpoint_path(model_dir)
        if checkpoint is None:
            raise FileNotFoundError(f"recognition checkpoint not found under {model_dir}")
        if bool(load_recognition_manifest(checkpoint).get("orders_enabled")):
            logger.warning(
                "recognition_orders_flag_ignored",
                checkpoint=str(checkpoint),
            )
        artifact = load_recognition_checkpoint(checkpoint)
        manifest = load_recognition_manifest(checkpoint)
        manifest["orders_enabled"] = False
        return cls(checkpoint, artifact, manifest)

    async def initialize(self) -> None:
        """Mark the loaded checkpoint ready for inference."""
        if "model" not in self._artifact:
            raise RuntimeError("recognition checkpoint has no model")
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "recognition_node_initialized",
            model_name=self._model_name,
            checkpoint=str(self._checkpoint),
            spec_version=self._model_version,
        )

    def _sync_predict_impl(self, ctx: Dict[str, Any]) -> MCPModelPrediction:
        t0 = time.perf_counter()
        if not self._initialized:
            raise RuntimeError("RecognitionModelNode is not initialized")
        frame = _frame_from_context(ctx)
        if frame is None:
            raise ValueError("recognition predict requires v43_df5m")
        recognized = predict_latest(self._artifact, frame)
        elapsed = (time.perf_counter() - t0) * 1000.0
        state = str(recognized.get("market_state") or "")
        names = [
            str(item.get("geometric_class"))
            for item in recognized.get("geometry") or []
            if isinstance(item, dict)
        ]
        detail = ", ".join(names) if names else "no geometric family"
        probability = float(recognized.get("market_state_probability") or 0.0)
        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=0.0,
            confidence=probability,
            reasoning=f"{RECOGNITION_DECISION_PATH} {state}: {detail}",
            features_used=list(ENGINEERED_CHANNELS),
            feature_importance={},
            computation_time_ms=float(elapsed),
            health_status=self._health,
            context=recognized,
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
            logger.error("recognition_predict_failed", error=str(exc), exc_info=True)
            raise

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "model_version": self._model_version,
            "model_type": self.model_type,
            "resolution": self.resolution,
            "checkpoint": str(self._checkpoint),
            "spec_version": self._model_version,
            "orders_enabled": False,
            "features_required": [],
        }

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health,
            "health_status": self._health,
            "model_loaded": self._initialized,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
        }
