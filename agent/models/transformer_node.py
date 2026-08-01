"""ONNX transformer MCP model node for per-TF BTCUSD bundles."""

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
from agent.core.mtf_decision_policy import resolution_to_ctx_key, resolution_to_tf_key
from agent.core.v43_market_frames import closed_5m_bar_index
from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from agent.models.transformer_context_builder import build_transformer_prediction_context
from feature_store.transformer_btcusd.contract import (
    FEATURE_COLS,
    RESOLUTION_MINUTES,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    onnx_filename_for_resolution,
)
from feature_store.transformer_btcusd.features import (
    build_feature_matrix,
    latest_closed_feature_row,
    prepare_raw_frame,
    validate_feature_columns,
)
from feature_store.transformer_btcusd.inference import (
    build_inference_window,
    parse_regime_prediction,
    resolve_feature_config,
    unstandardize_continuous,
)

logger = structlog.get_logger()

_LEGACY_MODEL_FAMILY = "jacksparrow_transformer_btcusd_15m"


def _ctx_dataframe(ctx: Dict[str, Any], primary_key: str, fallback_key: str) -> Optional[pd.DataFrame]:
    value = ctx.get(primary_key)
    if isinstance(value, pd.DataFrame):
        return value
    value = ctx.get(fallback_key)
    if isinstance(value, pd.DataFrame):
        return value
    return None


def _is_transformer_family(family: str) -> bool:
    fam = str(family or "").strip()
    if fam == _LEGACY_MODEL_FAMILY:
        return True
    return fam.startswith("jacksparrow_transformer_btcusd_")


class TransformerModelNode(MCPModelNode):
    """Loads Colab-exported per-TF ONNX transformer and emits prediction context."""

    def __init__(
        self,
        metadata_path: Path,
        bundle_metadata: Dict[str, Any],
        feature_config: Dict[str, Any],
        onnx_path: Path,
    ) -> None:
        self._metadata_path = metadata_path
        self._bundle_dir = metadata_path.parent
        self._bundle_meta = bundle_metadata
        self._feature_config = feature_config
        self._onnx_path = onnx_path
        self._model_name = str(
            bundle_metadata.get("model_name") or "jacksparrow_transformer_BTCUSD"
        )
        self._model_version = str(bundle_metadata.get("version") or "transformer_v1")
        self._resolution = str(bundle_metadata.get("resolution") or "15m").lower()
        self._resolution_minutes = int(
            bundle_metadata.get("resolution_minutes")
            or RESOLUTION_MINUTES.get(self._resolution, 15)
        )
        self._session: Any = None
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
        return "transformer"

    @property
    def resolution(self) -> str:
        return self._resolution

    @property
    def tf_key(self) -> str:
        return resolution_to_tf_key(self._resolution)

    @property
    def _bundle_metadata(self) -> Dict[str, Any]:
        return self._bundle_meta

    @property
    def training_forward_bars(self) -> int:
        cfg = self._feature_config.get("config") or {}
        return int(
            cfg.get("path_label_horizon_bars")
            or self._bundle_meta.get("path_label_horizon_bars")
            or 8
        )

    @classmethod
    def from_metadata_path(cls, meta_path: Path) -> "TransformerModelNode":
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Transformer metadata must be a JSON object: {meta_path}")
        family = str(raw.get("model_family") or "").strip()
        if not _is_transformer_family(family):
            raise ValueError(
                f"{TRANSFORMER_METADATA_FILENAME} model_family must be "
                f"jacksparrow_transformer_btcusd_<resolution>, got {family!r}"
            )

        bundle_dir = meta_path.parent
        feature_config = resolve_feature_config(bundle_dir)
        resolution = str(raw.get("resolution") or "15m")
        onnx_name = str(
            raw.get("onnx_filename") or onnx_filename_for_resolution(resolution)
        )
        onnx_path = bundle_dir / onnx_name
        if not onnx_path.is_file():
            raise FileNotFoundError(
                f"ONNX artifact not found: {onnx_path}. "
                f"Copy {onnx_name} from Colab into the model bundle."
            )
        return cls(meta_path, raw, feature_config, onnx_path)

    async def initialize(self) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is required for TransformerModelNode; "
                "install agent/requirements.txt"
            ) from exc

        self._session = ort.InferenceSession(
            str(self._onnx_path),
            providers=["CPUExecutionProvider"],
        )
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "transformer_node_initialized",
            model_name=self._model_name,
            resolution=self._resolution,
            metadata=str(self._metadata_path),
            onnx=str(self._onnx_path),
            window_len=self._feature_config.get("window_len"),
        )

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
            "onnx_path": str(self._onnx_path),
            "resolution": self._resolution,
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "version": self._model_version,
            "model_type": self.model_type,
            "resolution": self._resolution,
            "features_required": list(self._feature_config.get("feature_cols") or FEATURE_COLS),
            "feature_list": list(self._feature_config.get("feature_cols") or FEATURE_COLS),
            "description": f"BTCUSD {self._resolution} transformer ONNX (Colab-trained)",
            "metadata_path": str(self._metadata_path),
            "onnx_path": str(self._onnx_path),
            "model_family": str(self._bundle_meta.get("model_family") or ""),
            "window_len": self._feature_config.get("window_len"),
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
            logger.error(
                "transformer_predict_failed",
                model_name=self._model_name,
                resolution=self._resolution,
                error=str(exc),
                exc_info=True,
            )
            raise

    def _resolve_ohlcv_frame(self, ctx: Dict[str, Any]) -> pd.DataFrame:
        ctx_key = resolution_to_ctx_key(self._resolution)
        fallback = f"df{self._resolution}"
        df = _ctx_dataframe(ctx, ctx_key, fallback)
        if not isinstance(df, pd.DataFrame) or df.empty:
            raise ValueError(
                f"Transformer {self._resolution} predict requires {ctx_key} "
                "as non-empty pd.DataFrame"
            )
        return df

    def _sync_predict_impl(self, ctx: Dict[str, Any]) -> MCPModelPrediction:
        t0 = time.perf_counter()
        if self._session is None:
            raise RuntimeError("TransformerModelNode not initialized")

        df_ohlcv = self._resolve_ohlcv_frame(ctx)
        df_fund = _ctx_dataframe(ctx, "v43_df_funding", "df_funding")
        df_oi = _ctx_dataframe(ctx, "v43_df_oi", "df_oi")
        df5 = _ctx_dataframe(ctx, "v43_df5m", "df5m")

        raw = prepare_raw_frame(df_ohlcv, funding_df=df_fund, oi_df=df_oi)
        atr_period = int(
            (self._feature_config.get("config") or {}).get("atr_period")
            or self._bundle_meta.get("atr_period")
            or 14
        )
        feat_df = build_feature_matrix(
            raw,
            resolution_minutes=self._resolution_minutes,
            atr_period=atr_period,
            dropna=True,
        )
        validate_feature_columns(feat_df)

        feature_cols = list(self._feature_config.get("feature_cols") or FEATURE_COLS)
        window_len = int(self._feature_config.get("window_len") or 128)
        values = feat_df[feature_cols].values.astype(np.float32)
        window = build_inference_window(values, window_len=window_len, feature_cols=feature_cols)

        continuous_z, regime_logits = self._session.run(None, {"window": window})
        continuous_preds = unstandardize_continuous(
            continuous_z[0],
            self._feature_config["label_mean"],
            self._feature_config["label_std"],
            label_cols=self._feature_config.get("continuous_label_cols") or [],
        )
        regime_names = self._feature_config.get("regime_names") or {
            "0": "LOW",
            "1": "NORMAL",
            "2": "HIGH",
            "3": "EXTREME",
        }
        _, vol_regime, regime_probs = parse_regime_prediction(regime_logits[0], regime_names)

        bar_hint = 0
        if isinstance(df5, pd.DataFrame) and not df5.empty:
            bar_hint = int(closed_5m_bar_index(df5))

        closed_row = latest_closed_feature_row(feat_df)
        closed_feats = {
            str(k): float(closed_row[k])
            for k in feature_cols
            if k in closed_row.index and pd.notna(closed_row[k]) and np.isfinite(closed_row[k])
        }

        out_ctx, pred_val, conf = build_transformer_prediction_context(
            bundle_metadata=self._bundle_meta,
            continuous_preds=continuous_preds,
            vol_regime=vol_regime,
            regime_probs=regime_probs,
            bar_index_hint=bar_hint,
            resolution_minutes=self._resolution_minutes,
        )
        out_ctx["closed_bar_features"] = closed_feats
        out_ctx["tf_key"] = self.tf_key

        ms = (time.perf_counter() - t0) * 1000.0
        er = float(out_ctx.get("expected_return", 0.0))
        thr = float(out_ctx.get("threshold", 0.005))
        regime = str(out_ctx.get("regime", "neutral"))
        reasoning = (
            f"Transformer {self._resolution} regime={regime} vol={vol_regime} "
            f"er={er:.5f} thr={thr:.5f}"
        )

        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=pred_val,
            confidence=conf,
            reasoning=reasoning,
            features_used=list(feature_cols),
            feature_importance={},
            computation_time_ms=ms,
            health_status="healthy",
            context=out_ctx,
        )
