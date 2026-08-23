"""ONNX node for the single multi-TF fusion bundle."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

from agent.models.mcp_model_node import MCPModelNode, MCPModelPrediction, MCPModelRequest
from feature_store.transformer_btcusd.contract import (
    FEATURE_CONTRACT_VERSION_V10,
    FUSION_HORIZON_KEYS,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_MODEL_FAMILY,
    FUSION_ONNX_FILENAME,
    FUSION_WINDOW_LEN,
    ONNX_OUTPUT_NAMES_V10,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
)
from feature_store.transformer_btcusd.inference import (
    load_feature_config,
    require_onnx_output_names,
)
from feature_store.transformer_btcusd.mtf_features import encode_all_tf_windows
from feature_store.transformer_btcusd.mtf_frames import (
    bar_close_time,
    build_10m_ohlcv_from_5m,
    fusion_frames_from_fetch,
)

logger = structlog.get_logger()


def _ctx_df(ctx: Dict[str, Any], *keys: str) -> Optional[pd.DataFrame]:
    for key in keys:
        value = ctx.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            return value
    return None


class FusionModelNode(MCPModelNode):
    """Loads the v10 fused ONNX bundle and emits per-horizon logits."""

    def __init__(
        self,
        metadata_path: Path,
        bundle_metadata: Dict[str, Any],
        feature_config: Dict[str, Any],
        onnx_path: Path,
    ) -> None:
        self._metadata_path = metadata_path
        self._bundle_meta = bundle_metadata
        self._feature_config = feature_config
        self._onnx_path = onnx_path
        self._session: Any = None
        self._initialized = False
        self._health = "unknown"
        self._call_count = 0
        self._error_count = 0
        self._model_name = str(
            bundle_metadata.get("model_name") or "jacksparrow_transformer_BTCUSD_mtf_fusion"
        )
        self._model_version = str(bundle_metadata.get("version") or "transformer_mtf_fusion_v10")
        self._window_len = int(feature_config.get("window_len") or FUSION_WINDOW_LEN)
        self._input_names: List[str] = list(
            feature_config.get("input_names")
            or [f"features_{res}" for res in FUSION_INPUT_RESOLUTIONS]
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return "transformer_mtf_fusion"

    @property
    def resolution(self) -> str:
        return "mtf_fusion"

    @classmethod
    def from_metadata_path(cls, meta_path: Path) -> "FusionModelNode":
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Fusion metadata must be a JSON object: {meta_path}")
        family = str(raw.get("model_family") or "").strip()
        if family != FUSION_MODEL_FAMILY:
            raise ValueError(
                f"{TRANSFORMER_METADATA_FILENAME} model_family must be "
                f"{FUSION_MODEL_FAMILY}, got {family!r}"
            )
        bundle_dir = meta_path.parent
        cfg_path = bundle_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
        feature_config = load_feature_config(cfg_path)
        contract = str(feature_config.get("feature_contract_version") or "")
        if contract and contract != FEATURE_CONTRACT_VERSION_V10:
            raise RuntimeError(
                f"Fusion bundle contract {contract!r} is not {FEATURE_CONTRACT_VERSION_V10}"
            )
        onnx_name = str(raw.get("onnx_filename") or FUSION_ONNX_FILENAME)
        onnx_path = bundle_dir / onnx_name
        if not onnx_path.is_file():
            raise FileNotFoundError(f"ONNX artifact not found: {onnx_path}")
        return cls(meta_path, raw, feature_config, onnx_path)

    async def initialize(self) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is required for FusionModelNode"
            ) from exc
        self._session = ort.InferenceSession(
            str(self._onnx_path),
            providers=["CPUExecutionProvider"],
        )
        require_onnx_output_names(
            [o.name for o in self._session.get_outputs()],
            contract_version=FEATURE_CONTRACT_VERSION_V10,
            resolution="mtf_fusion",
        )
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "fusion_node_initialized",
            model_name=self._model_name,
            onnx=str(self._onnx_path),
        )

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
            "onnx_path": str(self._onnx_path),
            "resolution": self.resolution,
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "version": self._model_version,
            "model_type": self.model_type,
            "resolution": self.resolution,
            "model_family": FUSION_MODEL_FAMILY,
            "window_len": self._window_len,
            "onnx_output_names": list(ONNX_OUTPUT_NAMES_V10),
            "horizon_gates": dict(self._feature_config.get("horizon_gates") or {}),
        }

    def _frames_from_context(self, ctx: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        df5 = _ctx_df(ctx, "v43_df5m", "df5m")
        if df5 is None:
            raise ValueError("Fusion predict requires v43_df5m")
        df10 = _ctx_df(ctx, "v43_df10m", "df10m")
        if df10 is None:
            df10 = build_10m_ohlcv_from_5m(df5)
        df30 = _ctx_df(ctx, "v43_df30m", "df30m")
        df1h = _ctx_df(ctx, "v43_df1h", "df1h")
        df2h = _ctx_df(ctx, "v43_df2h", "df2h")
        if df30 is None or df1h is None or df2h is None:
            raise ValueError("Fusion predict requires 30m/1h/2h OHLCV frames")
        return fusion_frames_from_fetch(df5, df30, df1h, df2h, df10m=df10)

    def _decision_time(self, df5: pd.DataFrame) -> pd.Timestamp:
        frame = df5.copy()
        col = "time" if "time" in frame.columns else "timestamp"
        times = pd.to_datetime(frame[col], utc=True)
        if len(times) < 2:
            raise ValueError("Need at least 2 five-minute bars")
        last_open = times.iloc[-2]
        return bar_close_time(pd.Series([last_open]), 5).iloc[0]

    def _sync_predict_impl(self, ctx: Dict[str, Any]) -> MCPModelPrediction:
        t0 = time.perf_counter()
        frames = self._frames_from_context(ctx)
        df5 = frames["5m"]
        decision_time = self._decision_time(df5)
        funding = _ctx_df(ctx, "v43_df_funding", "df_funding")
        oi = _ctx_df(ctx, "v43_df_oi", "df_oi")
        windows = encode_all_tf_windows(
            frames,
            decision_time,
            window_len=self._window_len,
            funding_df=funding,
            oi_df=oi,
            zscore=True,
        )
        feeds = {
            name: np.asarray(windows[res], dtype=np.float32)[np.newaxis, ...]
            for name, res in zip(self._input_names, FUSION_INPUT_RESOLUTIONS)
        }
        if self._session is None:
            raise RuntimeError("FusionModelNode is not initialized")
        named_out = self._session.run(None, feeds)
        out_names = [o.name for o in self._session.get_outputs()]
        named = {n: v for n, v in zip(out_names, named_out)}
        horizon_logits: Dict[str, List[float]] = {}
        for key in FUSION_HORIZON_KEYS:
            arr = np.asarray(named[f"{key}_dir_logits"][0], dtype=np.float64)
            horizon_logits[key] = [float(x) for x in arr.tolist()]
        fusion_logits = [float(x) for x in np.asarray(named["tf_fusion_logits"][0]).tolist()]
        elapsed = (time.perf_counter() - t0) * 1000.0
        context = {
            "tf_key": "mtf_fusion",
            "resolution": "mtf_fusion",
            "horizon_logits": horizon_logits,
            "tf_fusion_logits": fusion_logits,
            "horizon_gates": dict(
                (self._feature_config.get("horizon_gates") or self._bundle_meta.get("horizon_gates") or {})
            ),
            "decision_time": str(decision_time),
            "window_len": self._window_len,
        }
        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=0.0,
            confidence=0.0,
            reasoning="mtf_fusion logits",
            features_used=list(FUSION_INPUT_RESOLUTIONS),
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
            logger.error("fusion_predict_failed", error=str(exc), exc_info=True)
            raise
