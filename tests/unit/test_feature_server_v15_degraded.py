"""v15 feature server: degraded placeholders when Delta returns no candles."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_store.feature_registry import V15_FEATURES_5M
from agent.data.feature_server import MCPFeatureRequest, MCPFeatureServer, FeatureQuality


@pytest.mark.asyncio
async def test_v15_returns_degraded_features_when_no_candles(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = MCPFeatureServer()
    srv.market_data_service = MagicMock()
    srv.market_data_service.get_market_data = AsyncMock(return_value=None)

    req = MCPFeatureRequest(
        feature_names=list(V15_FEATURES_5M),
        symbol="BTCUSD",
        candle_interval="5m",
        timestamp=datetime.utcnow(),
    )
    resp = await srv._get_v15_feature_response(
        req, "5m", "test-req-id", req.timestamp or datetime.utcnow()
    )
    assert len(resp.features) == len(V15_FEATURES_5M)
    assert resp.overall_quality == FeatureQuality.DEGRADED
    assert all(f.value == 0.0 for f in resp.features)
    assert all(f.metadata.get("reason") == "no_candles" for f in resp.features)
