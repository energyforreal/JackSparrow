"""Research node for support and resistance effectiveness.

The node never contributes an order.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from agent.models.swinging_bundle import load_research_bundle, vector_from_features
from research.swinging.contract import SPEC_VERSION, SR_BUNDLE_DIR
from research.swinging.features import snapshot_features
from research.swinging.models import score_features

logger = structlog.get_logger()


class SREffectivenessNode(MCPModelNode):
    """Scores bounce, rejection, breakout, and failed-breakout probabilities."""

    contributes_to_consensus = False

    def __init__(self, bundle_dir: Path, loaded: dict[str, Any]) -> None:
        self._bundle_dir = bundle_dir
        self._manifest = loaded["manifest"]
        self._artifact = loaded["artifact"]
        self._columns = list(loaded["feature_columns"])
        self._model_name = str(
            self._manifest.get("model_name") or "jacksparrow_sr_effectiveness_BTCUSD"
        )
        self._model_version = str(self._manifest.get("spec_version") or SPEC_VERSION)
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
        return "swinging_sr_effectiveness"

    @classmethod
    def from_model_dir(cls, model_dir: Path) -> "SREffectivenessNode":
        """Load the research bundle stored beside the other model directories.

        Args:
            model_dir: ``MODEL_DIR``.

        Returns:
            An uninitialized node.

        Raises:
            FileNotFoundError: If the bundle is absent.
            RuntimeError: If the bundle is allowed to place orders.
        """
        bundle = Path(model_dir) / SR_BUNDLE_DIR
        return cls(bundle, load_research_bundle(bundle))

    async def initialize(self) -> None:
        """Mark the artifact ready for inference."""
        if self._artifact.get("classifier") is None:
            raise RuntimeError("sr effectiveness bundle has no classifier")
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "sr_effectiveness_initialized",
            model_name=self._model_name,
            bundle=str(self._bundle_dir),
        )

    def _features_from_context(self, context: dict[str, Any]) -> dict[str, Any]:
        supplied = context.get("features")
        if isinstance(supplied, dict):
            return supplied
        frame = None
        for key in ("swinging_frame", "ohlcv"):
            value = context.get(key)
            if isinstance(value, pd.DataFrame) and not value.empty:
                frame = value
                break
        if frame is None:
            raise ValueError("sr effectiveness predict requires features or an OHLCV frame")
        resolution = str(context.get("resolution") or "1h")
        return snapshot_features(frame, len(frame) - 1, resolution)

    def _sync_predict(self, context: dict[str, Any]) -> MCPModelPrediction:
        started = time.perf_counter()
        if not self._initialized:
            raise RuntimeError("SREffectivenessNode is not initialized")
        features = self._features_from_context(context)
        values = np.asarray([vector_from_features(self._columns, features)], dtype=float)
        scored = score_features(self._artifact, values)
        probabilities = scored["class_probabilities"][0]
        top_name = max(probabilities, key=probabilities.get)
        probability = float(probabilities[top_name])
        expected = float(scored["expected_net_return"][0])
        elapsed = (time.perf_counter() - started) * 1000.0
        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=float(np.clip(expected, -1.0, 1.0)),
            confidence=float(np.clip(probability, 0.0, 1.0)),
            reasoning=f"sr effectiveness research score {top_name}; orders_enabled is false",
            features_used=self._columns,
            feature_importance={},
            computation_time_ms=float(elapsed),
            health_status=self._health,
            context={
                "orders_enabled": False,
                "promotion_status": "research",
                "contributes_to_consensus": False,
                "top_class": top_name,
                "class_probabilities": probabilities,
                "expected_net_return": expected,
            },
        )

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        self._call_count += 1
        try:
            import asyncio

            prediction = await asyncio.to_thread(self._sync_predict, request.context or {})
            self._health = "healthy"
            return prediction
        except Exception as exc:
            self._error_count += 1
            self._health = "degraded"
            logger.error("sr_effectiveness_predict_failed", error=str(exc), exc_info=True)
            raise

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": self._model_name,
            "model_version": self._model_version,
            "model_type": self.model_type,
            "orders_enabled": False,
            "promotion_status": "research",
            "contributes_to_consensus": False,
            "features_required": self._columns,
        }

    async def get_health_status(self) -> dict[str, Any]:
        return {
            "status": self._health,
            "health_status": self._health,
            "model_loaded": self._initialized,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
        }
