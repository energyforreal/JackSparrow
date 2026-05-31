"""MCP model node for JackSparrow MSO v50 market-state classifiers."""

from __future__ import annotations

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

from agent.models import market_state_shims as _mso_shims  # noqa: F401
from agent.core.config import settings
from agent.models.mcp_model_node import (
    MCPModelNode,
    MCPModelPrediction,
    MCPModelRequest,
    MarketStateIntelligence,
)
from agent.models.market_state_shims import MarketStateBundleExport
from feature_store.jacksparrow_mso_feature_extensions import (
    MSO_FEATURE_COLS,
    build_mso_feature_matrix,
    build_mso_last_row,
)
from feature_store.jacksparrow_mso_labels import (
    MSO_MODEL_FAMILY,
    TREND_REGIME_CLASSES,
)
from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix

logger = structlog.get_logger()

MSO_METADATA_FILENAME = "metadata_mso_v50.json"
MSO_ARTIFACT_FILENAMES = (
    "model_artifact_mso_v50.pkl",
    "model_artifact_mso_v50_patched.pkl",
)


class InsufficientRealDataError(RuntimeError):
    """Raised when live OI/funding data is stale or synthetic — MSO prediction blocked."""


def _ctx_dataframe(ctx: Dict[str, Any], primary_key: str, fallback_key: str) -> Optional[pd.DataFrame]:
    v = ctx.get(primary_key)
    if isinstance(v, pd.DataFrame):
        return v
    v = ctx.get(fallback_key)
    if isinstance(v, pd.DataFrame):
        return v
    return None


def _scalar_from_trend_proba(horizon_state: Dict[str, Any]) -> float:
    """Backward-compatible signed signal from 30m trend regime probabilities."""
    proba = horizon_state.get("trend_regime_proba")
    if not isinstance(proba, dict):
        label = str(horizon_state.get("trend_regime") or "RANGE")
        mapping = {
            "STRONG_BULL": 0.85,
            "WEAK_BULL": 0.45,
            "BULL": 0.55,
            "RANGE": 0.0,
            "WEAK_BEAR": -0.45,
            "STRONG_BEAR": -0.85,
            "BEAR": -0.55,
        }
        return float(mapping.get(label, 0.0))
    p_up = (
        float(proba.get("STRONG_BULL", 0))
        + float(proba.get("WEAK_BULL", 0))
        + float(proba.get("BULL", 0))
    )
    p_dn = (
        float(proba.get("STRONG_BEAR", 0))
        + float(proba.get("WEAK_BEAR", 0))
        + float(proba.get("BEAR", 0))
    )
    return float(np.clip(p_up - p_dn, -1.0, 1.0))


class MarketStateOracleNode(MCPModelNode):
    """Multi-horizon market-state oracle (classification heads, not return regression)."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        metadata_path: Path,
        feature_cols: List[str],
    ) -> None:
        self._model_name = model_name
        self._model_version = model_version
        self._metadata_path = metadata_path
        self._feature_cols = list(feature_cols)
        self._bundle_dir = metadata_path.parent
        self._bundle: Optional[MarketStateBundleExport] = None
        self._metadata: Dict[str, Any] = {}
        self._initialized = False
        self._health = "unknown"
        self._last_oi_fetch_ts: float = 0.0
        self._last_oi_value: float = -1.0

    @classmethod
    def from_metadata_path(cls, metadata_path: Path) -> "MarketStateOracleNode":
        with metadata_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        if str(meta.get("model_family") or "") != MSO_MODEL_FAMILY:
            raise ValueError(
                f"Expected model_family={MSO_MODEL_FAMILY!r}, got {meta.get('model_family')!r}"
            )
        name = str(meta.get("model_name") or "jacksparrow_mso_v50_BTCUSD")
        ver = str(meta.get("version") or meta.get("version_tag") or "v50")
        feats = list(meta.get("features") or MSO_FEATURE_COLS)
        node = cls(
            model_name=name,
            model_version=ver,
            metadata_path=metadata_path,
            feature_cols=feats,
        )
        node._metadata = meta
        return node

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return "market_state_oracle"

    def _resolve_artifact_path(self) -> Path:
        for name in MSO_ARTIFACT_FILENAMES:
            p = self._bundle_dir / name
            if p.is_file():
                return p
        raise FileNotFoundError(
            f"MSO artifact missing under {self._bundle_dir}: tried {MSO_ARTIFACT_FILENAMES}"
        )

    def _check_live_data_freshness(self, ctx: Dict[str, Any]) -> None:
        if not bool(getattr(settings, "mso_require_real_oi", True)):
            return
        oi_ts = ctx.get("mso_oi_snapshot_ts")
        oi_val = ctx.get("mso_oi_contracts")
        if oi_ts is not None:
            self._last_oi_fetch_ts = float(oi_ts)
        if oi_val is not None:
            self._last_oi_value = float(oi_val)
        max_stale = float(getattr(settings, "mso_oi_max_staleness_seconds", 600) or 600)
        if self._last_oi_fetch_ts > 0:
            age = time.time() - self._last_oi_fetch_ts
            if age > max_stale:
                raise InsufficientRealDataError(
                    f"OI ring buffer stale ({age:.0f}s > {max_stale:.0f}s). MSO blocked."
                )
        if self._last_oi_value == 0.0:
            raise InsufficientRealDataError(
                "OI value is zero — synthetic fallback detected. MSO blocked."
            )

    async def initialize(self) -> None:
        if bool(getattr(settings, "mso_require_export_gates", True)):
            passed = self._metadata.get("export_gate_passed")
            if passed is False:
                scope = self._metadata.get("export_gate_scope", "unknown")
                results = self._metadata.get("export_gate_results") or []
                preview = "; ".join(str(r) for r in results[:5])
                raise RuntimeError(
                    f"MSO bundle failed export gates (scope={scope}). "
                    f"Refusing to load. Failures: {preview}"
                )
        artifact_path = self._resolve_artifact_path()
        loaded = _load(artifact_path)
        if isinstance(loaded, MarketStateBundleExport):
            self._bundle = loaded
        elif isinstance(loaded, dict) and "horizon_models" in loaded:
            self._bundle = MarketStateBundleExport(**loaded)
        else:
            self._bundle = loaded
        self._initialized = True
        self._health = "healthy"
        logger.info(
            "mso_node_initialized",
            model_name=self._model_name,
            artifact=str(artifact_path),
        )

    def _build_feature_row(self, ctx: Dict[str, Any]) -> pd.DataFrame:
        df5 = _ctx_dataframe(ctx, "v43_df5m", "df5m")
        if df5 is None or df5.empty:
            raise ValueError("MSO predict requires v43_df5m DataFrame in context")
        df_fund = _ctx_dataframe(ctx, "v43_df_funding", "df_funding")
        df_oi = _ctx_dataframe(ctx, "v43_df_oi", "df_oi_hist")
        df_mark = _ctx_dataframe(ctx, "v43_df_mark", "df_mark")

        v43 = build_v43_feature_matrix(
            df5,
            df_funding=df_fund,
            df_oi=df_oi,
            df_mark=df_mark,
        )
        mso = build_mso_feature_matrix(v43, df_ohlcv=df5)
        return build_mso_last_row(mso, df_ohlcv=df5)

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        t0 = time.perf_counter()
        ctx = dict(request.context or {})
        self._check_live_data_freshness(ctx)
        if not self._initialized or self._bundle is None:
            await self.initialize()

        row = self._build_feature_row(ctx)
        cols = [c for c in self._feature_cols if c in row.columns]
        if len(cols) < len(self._feature_cols) * 0.9:
            missing = [c for c in self._feature_cols if c not in row.columns]
            raise ValueError(f"MSO feature row missing columns: {missing[:8]}")

        X_df = row[cols]
        bundle = self._bundle
        assert bundle is not None
        market_state: MarketStateIntelligence = bundle.predict_all_horizons(
            X_df.values, X_df=X_df
        )

        primary_hk = "intraday_30m"
        h_state = market_state.get(primary_hk) or {}
        scalar = _scalar_from_trend_proba(h_state)
        conf = float(min(1.0, max(0.0, abs(scalar))))

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        reasoning = (
            f"MSO v50 market state ({primary_hk}): "
            f"trend={h_state.get('trend_regime')}, "
            f"breakout={h_state.get('breakout_state')}, "
            f"liquidity={h_state.get('liquidity_condition')}"
        )

        meta_ctx: Dict[str, Any] = {
            "market_state": market_state,
            "mso_model_family": MSO_MODEL_FAMILY,
        }

        return MCPModelPrediction(
            model_name=self._model_name,
            model_version=self._model_version,
            prediction=scalar,
            confidence=conf,
            reasoning=reasoning,
            features_used=cols,
            feature_importance={},
            computation_time_ms=elapsed_ms,
            health_status=self._health,
            context=meta_ctx,
        )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name": self._model_name,
            "model_version": self._model_version,
            "model_type": self.model_type,
            "model_family": MSO_MODEL_FAMILY,
            "feature_count": len(self._feature_cols),
            "state_dimensions": list(
                getattr(self._bundle, "state_dimensions", ()) if self._bundle else ()
            ),
            "horizons": list(
                (self._bundle.horizon_models.keys() if self._bundle else [])
            ),
        }

    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "status": self._health if self._initialized else "not_initialized",
            "model_name": self._model_name,
            "initialized": self._initialized,
        }
