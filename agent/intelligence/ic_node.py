"""Rule-based Intelligence Component — MCP model node without ML artifacts."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

from agent.core.config import settings
from agent.core.v43_market_frames import closed_5m_bar_index
from agent.intelligence.ic_context_builder import build_ic_prediction_context
from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix
from feature_store.jacksparrow_v43_contract import (
    resolve_v43_feature_contract,
    validate_v43_metadata_compatibility,
)

logger = structlog.get_logger()

IC_MODEL_FAMILY = "jacksparrow_ic_rule_based"
IC_METADATA_FILENAME = "metadata_ic.json"


def _ctx_dataframe(ctx: Dict[str, Any], primary_key: str, fallback_key: str) -> Optional[pd.DataFrame]:
    v = ctx.get(primary_key)
    if isinstance(v, pd.DataFrame):
        return v
    v = ctx.get(fallback_key)
    if isinstance(v, pd.DataFrame):
        return v
    return None


class RuleBasedIntelligenceNode(MCPModelNode):
    """Deterministic intelligence layer implementing MCPModelNode."""

    def __init__(
        self,
        metadata_path: Path,
        bundle_metadata: Dict[str, Any],
        feature_names: List[str],
    ) -> None:
        self._metadata_path = metadata_path
        self._bundle_meta = bundle_metadata
        self._feature_names = feature_names
        self._model_name = str(
            bundle_metadata.get("model_name") or "jacksparrow_ic_BTCUSD"
        )
        self._model_version = str(bundle_metadata.get("version") or "ic_v1")
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
        return "rule_based_intelligence"

    @property
    def _bundle_metadata(self) -> Dict[str, Any]:
        """Orchestrator reads horizons/thresholds from bundle metadata."""
        return self._bundle_meta

    @property
    def training_forward_bars(self) -> int:
        return int(self._bundle_meta.get("primary_execution_horizon_bars", 2) or 2)

    @classmethod
    def from_metadata_path(cls, meta_path: Path) -> "RuleBasedIntelligenceNode":
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"IC metadata must be a JSON object: {meta_path}")
        family = str(raw.get("model_family") or "").strip()
        if family != IC_MODEL_FAMILY:
            raise ValueError(
                f"metadata_ic.json model_family must be {IC_MODEL_FAMILY!r}, got {family!r}"
            )
        validate_v43_metadata_compatibility(raw)
        _ver, features = resolve_v43_feature_contract(raw)
        return cls(meta_path, raw, list(features))

    async def initialize(self) -> None:
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "ic_node_initialized",
            model_name=self._model_name,
            metadata=str(self._metadata_path),
            feature_count=len(self._feature_names),
        )

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "version": self._model_version,
            "model_type": self.model_type,
            "features_required": list(self._feature_names),
            "feature_list": list(self._feature_names),
            "description": "Rule-based Intelligence Component (no ML artifacts)",
            "metadata_path": str(self._metadata_path),
            "model_family": IC_MODEL_FAMILY,
        }

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        self._call_count += 1
        t0 = time.perf_counter()
        try:
            pred = await asyncio.to_thread(self._sync_predict_impl, request.context or {})
            self._health = "healthy"
            return pred
        except Exception as exc:
            self._error_count += 1
            self._health = "degraded"
            logger.error("ic_predict_failed", error=str(exc), exc_info=True)
            raise

    def _sync_predict_impl(self, ctx: Dict[str, Any]) -> MCPModelPrediction:
        t0 = time.perf_counter()
        df5 = _ctx_dataframe(ctx, "v43_df5m", "df5m")
        df15 = _ctx_dataframe(ctx, "v43_df15m", "df15m")
        df1h = _ctx_dataframe(ctx, "v43_df1h", "df1h")
        df_fund = _ctx_dataframe(ctx, "v43_df_funding", "df_funding")
        df_oi = _ctx_dataframe(ctx, "v43_df_oi", "df_oi")
        df_mark = _ctx_dataframe(ctx, "v43_df_mark", "df_mark")

        if not isinstance(df5, pd.DataFrame):
            raise ValueError("IC predict requires v43_df5m as pd.DataFrame")
        if not isinstance(df_fund, pd.DataFrame):
            raise ValueError("IC predict requires v43_df_funding as pd.DataFrame")
        if df15 is None:
            df15 = pd.DataFrame()
        if df1h is None:
            df1h = pd.DataFrame()

        df_feat = build_v43_feature_matrix(
            df5,
            df15,
            df1h,
            df_fund,
            df_oi=df_oi,
            df_mark=df_mark,
            for_training=False,
        )
        if df_feat is None or len(df_feat) < 2:
            raise ValueError("IC feature matrix returned < 2 rows")

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

        short_enabled = bool(
            getattr(settings, "jacksparrow_v43_short_execution_enabled", False)
        )
        market_context = {k: v for k, v in ctx.items() if not k.startswith("v43_df")}
        out_ctx, pred_val, conf = build_ic_prediction_context(
            bundle_metadata=self._bundle_meta,
            closed_feats=closed_feats,
            market_context=market_context,
            bar_index_hint=int(closed_5m_bar_index(df5)),
            short_enabled=short_enabled,
        )

        ms = (time.perf_counter() - t0) * 1000.0
        regime = str(out_ctx.get("regime", "neutral"))
        er = float(out_ctx.get("expected_return", 0.0))
        thr = float(out_ctx.get("threshold", 0.005))
        reasoning = (
            f"IC rule-based regime={regime} er={er:.5f} thr={thr:.5f} "
            f"thesis={out_ctx.get('ic_thesis_signal')}"
        )

        use_cols = [c for c in self._feature_names if c in df_feat.columns]
        if len(use_cols) < len(self._feature_names) * 0.9:
            missing = sorted(set(self._feature_names) - set(use_cols))[:12]
            logger.warning(
                "ic_feature_columns_partial",
                found=len(use_cols),
                expected=len(self._feature_names),
                missing_sample=missing,
            )
        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=pred_val,
            confidence=conf,
            reasoning=reasoning,
            features_used=use_cols,
            feature_importance={},
            computation_time_ms=ms,
            health_status="healthy",
            context=out_ctx,
        )
