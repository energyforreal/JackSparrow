"""Runtime smoke for JackSparrowV43Node exported-bundle inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
from agent.models.mcp_model_node import MCPModelRequest

BUNDLE_DIR = Path("agent/model_storage/JackSparrow_v43_models_BTCUSD")
METADATA = BUNDLE_DIR / "metadata_v43.json"
ARTIFACT = BUNDLE_DIR / "model_artifact_v43.pkl"

pytestmark = pytest.mark.skipif(
    not (METADATA.is_file() and ARTIFACT.is_file()),
    reason="v43 model bundle not present",
)


def _synthetic_ohlcv(rows: int = 360) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    base = np.linspace(100_000.0, 101_000.0, rows)
    wave = np.sin(np.arange(rows) / 12.0) * 150.0
    close = base + wave
    open_ = close + np.cos(np.arange(rows) / 10.0) * 20.0
    high = np.maximum(open_, close) + 50.0
    low = np.minimum(open_, close) - 50.0
    volume = 100.0 + np.abs(np.sin(np.arange(rows) / 9.0)) * 20.0
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def _synthetic_funding(rows: int = 48) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=rows, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "funding_rate": np.sin(np.arange(rows) / 8.0) * 0.0001,
        }
    )


@pytest.mark.asyncio
async def test_v43_node_predict_emits_expected_return_context() -> None:
    node = JackSparrowV43Node.from_metadata_path(METADATA)
    await node.initialize()

    df5 = _synthetic_ohlcv()
    request = MCPModelRequest(
        request_id="runtime-smoke",
        features=[],
        context={
            "v43_df5m": df5,
            "v43_df15m": pd.DataFrame(),
            "v43_df1h": pd.DataFrame(),
            "v43_df_funding": _synthetic_funding(),
        },
        require_explanation=True,
    )

    prediction = await node.predict(request)
    assert prediction.health_status == "healthy"
    assert prediction.context is not None
    for key in (
        "expected_return",
        "threshold",
        "regime",
        "uncertainty",
        "unc_scale",
        "closed_bar_features",
    ):
        assert key in prediction.context
    assert np.isfinite(float(prediction.context["expected_return"]))
    assert float(prediction.context["threshold"]) >= 0.0
    assert prediction.context["closed_bar_features"]
