"""Parity tests for IncrementalFeatureEngine vs batch matrix path."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from agent.core.config import settings
from agent.data.incremental_feature_engine import IncrementalFeatureEngine
from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix


def _synthetic_frames(n: int = 120) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = int(datetime.now(timezone.utc).timestamp()) - n * 300
    rows = []
    for i in range(n):
        ts = base + i * 300
        px = 50_000.0 + i
        rows.append(
            {
                "timestamp": pd.Timestamp(ts, unit="s", tz="UTC"),
                "open": px,
                "high": px + 10,
                "low": px - 10,
                "close": px + 1,
                "volume": 100.0,
            }
        )
    df5 = pd.DataFrame(rows)
    df15 = df5.iloc[::3].reset_index(drop=True)
    df1h = df5.iloc[::12].reset_index(drop=True)
    df_fund = pd.DataFrame(
        {
            "timestamp": df1h["timestamp"],
            "funding_rate": 0.0001,
        }
    )
    return df5, df15, df1h, df_fund


def test_incremental_engine_matches_batch_closed_feats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "incremental_features_enabled", True)
    df5, df15, df1h, df_fund = _synthetic_frames()
    engine = IncrementalFeatureEngine()
    closed_inc, _ = engine.update_from_frames("BTCUSD", df5, df15, df1h, df_fund)
    closed_inc2, _ = engine.update_from_frames("BTCUSD", df5, df15, df1h, df_fund)

    df_feat = build_v43_feature_matrix(
        df5, df15, df1h, df_fund, for_training=False
    )
    assert df_feat is not None and len(df_feat) >= 2
    batch_row = df_feat.iloc[-2]
    batch_feats: dict[str, float] = {}
    for k in df_feat.columns:
        v = batch_row[k]
        if pd.isna(v):
            continue
        try:
            fv = float(v)
            if fv == fv:
                batch_feats[str(k)] = fv
        except (TypeError, ValueError):
            continue

    assert closed_inc2 == closed_inc
    overlap = set(closed_inc.keys()) & set(batch_feats.keys())
    assert len(overlap) > 20
    for key in sorted(overlap)[:30]:
        assert abs(closed_inc[key] - batch_feats[key]) < 1e-6
