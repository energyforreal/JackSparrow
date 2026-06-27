"""Incremental closed-bar feature state aligned with v43 feature matrix."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd
import structlog

from agent.core.config import settings
from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix
from feature_store.jacksparrow_v43_incremental_state import v43_incremental_state_registry

logger = structlog.get_logger()

_INCREMENTAL_TAIL_DEFAULT = 300


class IncrementalFeatureEngine:
    """Maintains last closed-bar features; batch bootstrap on gaps."""

    def __init__(self) -> None:
        self._closed_feats: Dict[str, Dict[str, float]] = {}
        self._df_feat: Dict[str, pd.DataFrame] = {}

    def snapshot(self, symbol: str) -> Optional[Dict[str, float]]:
        return self._closed_feats.get(str(symbol or "").strip().upper())

    def feature_matrix(self, symbol: str) -> Optional[pd.DataFrame]:
        return self._df_feat.get(str(symbol or "").strip().upper())

    def update_from_frames(
        self,
        symbol: str,
        df5: pd.DataFrame,
        df15: pd.DataFrame,
        df1h: pd.DataFrame,
        df_fund: pd.DataFrame,
        *,
        df_oi: Optional[pd.DataFrame] = None,
        df_mark: Optional[pd.DataFrame] = None,
        force_batch: bool = False,
    ) -> Tuple[Dict[str, float], pd.DataFrame]:
        """Compute closed-bar features from frames (batch path; incremental hook)."""
        sym = str(symbol or "").strip().upper()
        use_incremental = bool(getattr(settings, "incremental_features_enabled", False))
        tail_bars = int(
            getattr(settings, "incremental_feature_tail_bars", _INCREMENTAL_TAIL_DEFAULT)
            or _INCREMENTAL_TAIL_DEFAULT
        )

        if (
            use_incremental
            and not force_batch
            and sym in self._closed_feats
            and sym in self._df_feat
            and not self._detect_gap(df5, sym)
        ):
            cached_feats = self._closed_feats[sym]
            cached_df = self._df_feat[sym]
            if cached_feats and cached_df is not None and len(cached_df) >= 2:
                return cached_feats, cached_df

        df5_use = df5
        df15_use = df15
        df1h_use = df1h
        if use_incremental and not force_batch and len(df5) > tail_bars:
            df5_use = df5.tail(tail_bars).reset_index(drop=True)
            if df15 is not None and len(df15) > tail_bars // 3 + 5:
                df15_use = df15.tail(tail_bars // 3 + 5).reset_index(drop=True)
            if df1h is not None and len(df1h) > tail_bars // 12 + 5:
                df1h_use = df1h.tail(tail_bars // 12 + 5).reset_index(drop=True)

        df_feat = build_v43_feature_matrix(
            df5_use,
            df15_use,
            df1h_use,
            df_fund,
            df_oi=df_oi,
            df_mark=df_mark,
            for_training=False,
        )
        if df_feat is None or len(df_feat) < 2:
            raise ValueError("IncrementalFeatureEngine: feature matrix < 2 rows")

        closed_row = df_feat.iloc[-2]
        closed_feats: Dict[str, float] = {}
        for k in df_feat.columns:
            try:
                v = closed_row[k]
                if pd.isna(v):
                    continue
                fv = float(v)
                if fv == fv:
                    closed_feats[str(k)] = fv
            except (TypeError, ValueError):
                continue

        self._closed_feats[sym] = closed_feats
        self._df_feat[sym] = df_feat
        v43_incremental_state_registry.get(sym).note_matrix(df_feat)
        return closed_feats, df_feat

    def _detect_gap(self, df5: pd.DataFrame, symbol: str) -> bool:
        """True when 5m frame has a timestamp discontinuity vs last snapshot."""
        prev = self._df_feat.get(symbol)
        if prev is None or prev.empty or df5 is None or len(df5) < 2:
            return False
        if "timestamp" not in df5.columns or "timestamp" not in prev.columns:
            return False
        try:
            last_prev = pd.Timestamp(prev["timestamp"].iloc[-2])
            last_new = pd.Timestamp(df5["timestamp"].iloc[-2])
            delta_s = abs((last_new - last_prev).total_seconds())
            return delta_s > 600
        except (TypeError, ValueError):
            return False

    def clear(self, symbol: Optional[str] = None) -> None:
        if symbol:
            sym = str(symbol).strip().upper()
            self._closed_feats.pop(sym, None)
            self._df_feat.pop(sym, None)
        else:
            self._closed_feats.clear()
            self._df_feat.clear()


incremental_feature_engine = IncrementalFeatureEngine()
