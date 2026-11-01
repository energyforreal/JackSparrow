"""Agent integration for the 15-minute recognition checkpoint."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from agent.core.transformer_decision import _forecast_prediction, _recognition_context
from agent.models.mcp_model_node import MCPModelPrediction
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelRequest
from agent.models.recognition_node import RecognitionModelNode
from research.forecast_30m.contract_v5 import FORECAST_DECISION_PATH
from research.recognition_15m.contract import (
    ENGINEERED_CHANNELS,
    GEOMETRIC_CLASSES,
    MARKET_STATES,
    RECOGNITION_DECISION_PATH,
    STRUCTURE_TAGS,
)
from research.recognition_15m.inference import load_recognition_checkpoint, predict_latest
from research.recognition_15m.models import RecognitionTCN


def _tiny_checkpoint(path: Path, hidden: int = 4) -> None:
    """Save a randomly initialized recognition checkpoint."""
    model = RecognitionTCN(
        in_channels=len(ENGINEERED_CHANNELS),
        n_geometry=len(GEOMETRIC_CLASSES),
        n_states=len(MARKET_STATES),
        n_tags=len(STRUCTURE_TAGS),
        hidden=hidden,
        dilations=(1, 2),
    )
    torch.save(
        {
            "spec_version": "recognition-15m-v1",
            "state_dict": model.state_dict(),
            "best_params": {"hidden": hidden, "dilations": [1, 2]},
            "scaler_mean": np.zeros(len(ENGINEERED_CHANNELS), dtype=np.float32),
            "scaler_std": np.ones(len(ENGINEERED_CHANNELS), dtype=np.float32),
            "channels": list(ENGINEERED_CHANNELS),
        },
        path,
    )


def _swinging_5m(buckets: int = 180) -> pd.DataFrame:
    """15-minute groups whose closes oscillate enough to confirm both swings."""
    count = buckets * 3
    stamps = pd.date_range("2024-01-01", periods=count, freq="5min", tz="UTC")
    bucket_index = np.arange(count) // 3
    wave = 100.0 + 15.0 * np.sin(2.0 * np.pi * bucket_index / 24.0)
    return pd.DataFrame(
        {
            "time": stamps,
            "open": wave,
            "high": wave + 0.4,
            "low": wave - 0.4,
            "close": wave + 0.1,
            "volume": np.full(count, 2.0),
        }
    )


def test_predict_latest_reports_state_without_an_order(tmp_path: Path) -> None:
    """A completed window yields a market state and leaves orders disabled."""
    checkpoint = tmp_path / "tcn_colab.pt"
    _tiny_checkpoint(checkpoint)
    artifact = load_recognition_checkpoint(checkpoint)
    result = predict_latest(artifact, _swinging_5m())
    assert result["orders_enabled"] is False
    assert result["decision_path"] == RECOGNITION_DECISION_PATH
    assert result["market_state"] in MARKET_STATES
    assert result["structure_tag"] in STRUCTURE_TAGS


def test_forecast_selection_ignores_the_recognition_payload() -> None:
    """The order prediction is the forecast row even when recognition is first."""
    recognition = MCPModelPrediction(
        model_name="recognition",
        model_version="v1",
        prediction=0.9,
        confidence=0.9,
        reasoning="state",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status="healthy",
        context={"decision_path": RECOGNITION_DECISION_PATH, "orders_enabled": False},
    )
    forecast = MCPModelPrediction(
        model_name="forecast",
        model_version="v5",
        prediction=0.4,
        confidence=0.8,
        reasoning="direction",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status="healthy",
        context={
            "decision_path": FORECAST_DECISION_PATH,
            "orders_enabled": True,
            "direction": "BULLISH",
        },
    )
    selected = _forecast_prediction([recognition, forecast])
    assert selected.model_name == "forecast"
    attached = _recognition_context([recognition, forecast])
    assert attached is not None
    assert attached["orders_enabled"] is False


@pytest.mark.asyncio
async def test_recognition_node_scores_five_minute_bars(tmp_path: Path) -> None:
    """The node reads v43_df5m and returns a zero order score."""
    checkpoint = tmp_path / "tcn_colab.pt"
    _tiny_checkpoint(checkpoint)
    node = RecognitionModelNode(
        checkpoint,
        load_recognition_checkpoint(checkpoint),
        {"model_name": "jacksparrow_recognition_BTCUSD_15m", "orders_enabled": False},
    )
    await node.initialize()
    prediction = await node.predict(
        MCPModelRequest(
            request_id="rec-1",
            features=[],
            context={"v43_df5m": _swinging_5m()},
        )
    )
    assert prediction.prediction == 0.0
    assert prediction.context is not None
    assert prediction.context["orders_enabled"] is False
    assert node.contributes_to_consensus is False


@pytest.mark.asyncio
async def test_recognition_is_omitted_from_consensus(tmp_path: Path) -> None:
    """A zero recognition score does not pull the forecast consensus."""
    checkpoint = tmp_path / "tcn_colab.pt"
    _tiny_checkpoint(checkpoint)
    node = RecognitionModelNode(
        checkpoint,
        load_recognition_checkpoint(checkpoint),
        {"model_name": "jacksparrow_recognition_BTCUSD_15m", "orders_enabled": False},
    )
    await node.initialize()

    class _Forecast:
        model_name = "jacksparrow_forecast_BTCUSD_30m"
        model_version = "v5"
        model_type = "forecast_30m_xgb"
        contributes_to_consensus = True

        async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
            del request
            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=0.5,
                confidence=1.0,
                reasoning="forecast",
                features_used=[],
                feature_importance={},
                computation_time_ms=1.0,
                health_status="healthy",
                context={"decision_path": FORECAST_DECISION_PATH, "orders_enabled": True},
            )

        async def get_health_status(self) -> dict[str, str]:
            return {"health_status": "healthy"}

    registry = MCPModelRegistry()
    registry.register_model(_Forecast())
    registry.register_model(node)
    response = await registry.get_predictions(
        MCPModelRequest(
            request_id="both",
            features=[],
            context={"v43_df5m": _swinging_5m()},
        )
    )
    assert response.consensus_prediction == pytest.approx(0.5)
    assert any(
        pred.context and pred.context.get("decision_path") == RECOGNITION_DECISION_PATH
        for pred in response.predictions
    )
