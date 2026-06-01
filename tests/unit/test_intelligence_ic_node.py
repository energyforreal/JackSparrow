"""Unit tests for rule-based Intelligence Component."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agent.core.ml_validator import build_ml_validation_from_prediction
from agent.intelligence.ic_context_builder import build_ic_prediction_context
from agent.intelligence.ic_node import IC_MODEL_FAMILY, RuleBasedIntelligenceNode
from agent.intelligence.regime_classifier import classify_regime
from agent.models.mcp_model_node import MCPModelRequest
from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES, V43_COMPATIBLE_FEATURE_VERSION
from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEYS, V43_HORIZON_KEY_TO_BARS


def _minimal_ic_metadata() -> dict:
    thr = 0.005
    horizons = {}
    for key in V43_HORIZON_KEYS:
        fb = V43_HORIZON_KEY_TO_BARS[key]
        horizons[key] = {
            "forward_bars": fb,
            "horizon_minutes": fb * 5,
            "horizon_key": key,
            "validation_metrics": {
                "dynamic_threshold": thr,
                "short_threshold": thr,
            },
            "dynamic_threshold": thr,
            "short_threshold": thr,
        }
    return {
        "version": "ic_v1",
        "model_name": "jacksparrow_ic_test",
        "model_family": IC_MODEL_FAMILY,
        "compatible_feature_version": V43_COMPATIBLE_FEATURE_VERSION,
        "features": list(V43_CANONICAL_FEATURES),
        "primary_execution_horizon_bars": 2,
        "horizons": horizons,
    }


def test_classify_regime_trending() -> None:
    feats = {"adx_14": 30.0, "hurst_60": 0.6, "atr_pct": 0.01, "vol_regime": 1.0}
    assert classify_regime(feats) == "trending"


def test_build_ic_context_multi_horizon_heads() -> None:
    meta = _minimal_ic_metadata()
    closed = {f: 0.0 for f in V43_CANONICAL_FEATURES}
    closed.update(
        {
            "adx_14": 28.0,
            "hurst_60": 0.56,
            "atr_pct": 0.012,
            "vol_regime": 1.1,
            "spread_bps": 20.0,
            "h_trend": 0.01,
            "h_rsi_14": 55.0,
            "h1_trend": 0.01,
            "h1_rsi_14": 54.0,
            "h1_adx": 22.0,
        }
    )
    ctx, pred_val, conf = build_ic_prediction_context(
        bundle_metadata=meta,
        closed_feats=closed,
        market_context={"features": closed},
        bar_index_hint=100,
        short_enabled=False,
    )
    heads = ctx.get("multi_horizon_heads")
    assert isinstance(heads, dict)
    assert set(heads.keys()) == set(V43_HORIZON_KEYS)
    for key in V43_HORIZON_KEYS:
        block = heads[key]
        assert "expected_return" in block
        assert "threshold" in block
        assert block["forward_bars"] == V43_HORIZON_KEY_TO_BARS[key]
    ml_val = build_ml_validation_from_prediction(
        ctx,
        pred_confidence=conf,
        pred_value=pred_val,
        eps=0.0,
        short_enabled=False,
    )
    assert ml_val.expected_return is not None
    assert isinstance(ml_val.threshold, float)


@pytest.mark.asyncio
async def test_ic_node_predict_requires_frames(tmp_path: Path) -> None:
    meta_path = tmp_path / "metadata_ic.json"
    meta_path.write_text(json.dumps(_minimal_ic_metadata()), encoding="utf-8")
    node = RuleBasedIntelligenceNode.from_metadata_path(meta_path)
    await node.initialize()

    n = 80
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    df5 = pd.DataFrame(
        {
            "timestamp": ts,
            "open": np.linspace(50000, 50100, n),
            "high": np.linspace(50010, 50110, n),
            "low": np.linspace(49990, 50090, n),
            "close": np.linspace(50000, 50100, n),
            "volume": np.full(n, 100.0),
        }
    )
    df_fund = pd.DataFrame({"timestamp": ts, "funding_rate": np.zeros(n)})
    req = MCPModelRequest(
        request_id="t1",
        features=[],
        context={"v43_df5m": df5, "v43_df_funding": df_fund},
    )
    pred = await node.predict(req)
    assert pred.health_status == "healthy"
    assert isinstance(pred.context, dict)
    assert pred.context.get("multi_horizon_heads")
