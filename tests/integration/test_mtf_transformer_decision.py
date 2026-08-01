"""Integration test: synthetic 5-TF predictions through MTF decision path."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from agent.core.transformer_decision import evaluate_transformer_prediction
from agent.models.mcp_model_node import MCPModelPrediction
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelResponse


def _ohlcv_df(n: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        },
        index=idx,
    )


def _prediction(
    resolution: str,
    *,
    future_return: float = 0.01,
    signal: str = "BUY",
) -> MCPModelPrediction:
    tf_key = f"tf_{resolution}"
    return MCPModelPrediction(
        model_name=f"jacksparrow_transformer_BTCUSD_{resolution}",
        model_version="transformer_per_tf_v1",
        prediction=1.0 if signal in ("BUY", "STRONG_BUY") else -1.0,
        confidence=0.75,
        reasoning=f"synthetic {resolution}",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status="healthy",
        context={
            "tf_key": tf_key,
            "resolution": resolution,
            "expected_return": future_return,
            "threshold": 0.005,
            "transformer_continuous_preds": {
                "future_return": future_return,
                "mfe": 0.02,
                "mae": 0.005,
                "future_volatility": 0.003,
                "trend_strength": 1.2,
            },
            "transformer_vol_regime": "NORMAL",
            "entry_confidence": 0.75,
            "regime": "trending",
            "closed_bar_features": {"ret_1": 0.001},
        },
    )


def _mock_registry(predictions: List[MCPModelPrediction]) -> MCPModelRegistry:
    registry = MagicMock(spec=MCPModelRegistry)
    registry.models = {p.model_name: MagicMock() for p in predictions}
    for pred in predictions:
        node = registry.models[pred.model_name]
        node.resolution = pred.context["resolution"]
        node._bundle_metadata = {"default_threshold": 0.005}

    async def _get_predictions(request: Any) -> MCPModelResponse:
        return MCPModelResponse(
            request_id=request.request_id,
            predictions=predictions,
            consensus_prediction=1.0,
            consensus_confidence=0.75,
            healthy_models=len(predictions),
            total_models=len(predictions),
            timestamp=datetime.now(timezone.utc),
        )

    registry.get_predictions = AsyncMock(side_effect=_get_predictions)
    registry.get_model = lambda name: registry.models.get(name)
    return registry


@pytest.mark.asyncio
async def test_mtf_decision_emits_multi_tf_context(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _ohlcv_df()
    frames = (df, df, df, df, df, df, df, df)

    async def _fetch_frames(_client: Any, _symbol: str) -> tuple:
        return frames

    monkeypatch.setattr(
        "agent.core.transformer_decision.fetch_mtf_market_frames",
        _fetch_frames,
    )

    contract_state = SimpleNamespace(
        is_operational=True,
        state="active",
        trading_status="open",
    )
    monkeypatch.setattr(
        "agent.core.v43_contract_state.get_contract_state",
        AsyncMock(return_value=contract_state),
    )

    portfolio_snap = SimpleNamespace(
        to_dict=lambda: {"exposure_pct": 0.0},
    )
    monkeypatch.setattr(
        "agent.core.portfolio_intelligence.fetch_portfolio_exposure_snapshot",
        AsyncMock(return_value=portfolio_snap),
    )
    monkeypatch.setattr(
        "agent.core.portfolio_intelligence.evaluate_portfolio_guard",
        lambda *_a, **_k: SimpleNamespace(
            allowed=True,
            reason_codes=[],
            to_dict=lambda: {"allowed": True},
        ),
    )
    monkeypatch.setattr(
        "agent.core.portfolio_intelligence.apply_portfolio_guard_to_verdict",
        lambda verdict, *_a, **_k: verdict,
    )

    predictions = [
        _prediction("5m"),
        _prediction("15m"),
        _prediction("30m"),
        _prediction("1h"),
        _prediction("2h"),
    ]
    registry = _mock_registry(predictions)

    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=registry,
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {
            "model_name": p.model_name,
            "confidence": p.confidence,
        },
    )

    mctx = result["market_context"]
    assert mctx["format"] == "jacksparrow_transformer_btcusd_mtf"
    assert "multi_tf_predictions" in mctx
    assert len(mctx["multi_tf_predictions"]) == 5
    assert "cross_tf_summary" in mctx
    assert result["decision"]["signal"] in ("BUY", "STRONG_BUY", "HOLD", "SELL", "STRONG_SELL")


@pytest.mark.asyncio
async def test_mtf_decision_bias_veto_forces_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _ohlcv_df()
    frames = (df, df, df, df, df, df, df, df)

    monkeypatch.setattr(
        "agent.core.transformer_decision.fetch_mtf_market_frames",
        AsyncMock(return_value=frames),
    )
    monkeypatch.setattr(
        "agent.core.v43_contract_state.get_contract_state",
        AsyncMock(
            return_value=SimpleNamespace(
                is_operational=True,
                state="active",
                trading_status="open",
            )
        ),
    )
    monkeypatch.setattr(
        "agent.core.portfolio_intelligence.fetch_portfolio_exposure_snapshot",
        AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {})),
    )
    monkeypatch.setattr(
        "agent.core.portfolio_intelligence.evaluate_portfolio_guard",
        lambda *_a, **_k: SimpleNamespace(
            allowed=True,
            reason_codes=[],
            to_dict=lambda: {},
        ),
    )
    monkeypatch.setattr(
        "agent.core.portfolio_intelligence.apply_portfolio_guard_to_verdict",
        lambda verdict, *_a, **_k: verdict,
    )

    predictions = [
        _prediction("5m", future_return=0.01),
        _prediction("15m", future_return=0.01),
        _prediction("30m", future_return=0.01),
        MCPModelPrediction(
            model_name="jacksparrow_transformer_BTCUSD_1h",
            model_version="v1",
            prediction=-1.0,
            confidence=0.8,
            reasoning="bearish 1h",
            features_used=[],
            feature_importance={},
            computation_time_ms=1.0,
            health_status="healthy",
            context={
                "tf_key": "tf_1h",
                "resolution": "1h",
                "expected_return": -0.01,
                "threshold": 0.005,
                "transformer_continuous_preds": {
                    "future_return": -0.01,
                    "mfe": 0.01,
                    "mae": 0.02,
                    "future_volatility": 0.004,
                    "trend_strength": 1.0,
                },
                "transformer_vol_regime": "NORMAL",
                "entry_confidence": 0.8,
                "regime": "bearish",
            },
        ),
        MCPModelPrediction(
            model_name="jacksparrow_transformer_BTCUSD_2h",
            model_version="v1",
            prediction=-1.0,
            confidence=0.8,
            reasoning="bearish 2h",
            features_used=[],
            feature_importance={},
            computation_time_ms=1.0,
            health_status="healthy",
            context={
                "tf_key": "tf_2h",
                "resolution": "2h",
                "expected_return": -0.01,
                "threshold": 0.005,
                "transformer_continuous_preds": {
                    "future_return": -0.01,
                    "mfe": 0.01,
                    "mae": 0.02,
                    "future_volatility": 0.004,
                    "trend_strength": 1.0,
                },
                "transformer_vol_regime": "NORMAL",
                "entry_confidence": 0.8,
                "regime": "bearish",
            },
        ),
    ]
    registry = _mock_registry(predictions)

    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=registry,
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )

    assert result["decision"]["signal"] == "HOLD"
    codes = result["market_context"].get("transformer_reason_codes") or []
    assert any("bias_veto" in c for c in codes)
