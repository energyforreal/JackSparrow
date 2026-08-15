"""Integration tests for climate/setup/timing agent synthesis decision path."""

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
    mfe: float = 0.02,
    mae: float = 0.005,
    vol_regime: str = "NORMAL",
    health: str = "healthy",
    trend_strength: float = 1.5,
    drawdown_before_mfe: float = 0.0,
    future_oi_change_pct: float = 0.05,
) -> MCPModelPrediction:
    tf_key = f"tf_{resolution}"
    path_edge = mfe - mae
    return MCPModelPrediction(
        model_name=f"jacksparrow_transformer_BTCUSD_{resolution}",
        model_version="transformer_per_tf_v1",
        prediction=1.0 if path_edge > 0 else -1.0,
        confidence=0.75,
        reasoning=f"synthetic {resolution}",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status=health,
        context={
            "tf_key": tf_key,
            "resolution": resolution,
            "path_edge": path_edge,
            "long_edge": path_edge,
            "short_edge": -path_edge,
            "threshold": 0.008,
            "transformer_continuous_preds": {
                "mfe": mfe,
                "mae": mae,
                "future_volatility": 0.003,
                "trend_strength": trend_strength,
                "drawdown_before_mfe": drawdown_before_mfe,
                "future_oi_change_pct": future_oi_change_pct,
            },
            "transformer_vol_regime": vol_regime,
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
        ctx = pred.context if isinstance(pred.context, dict) else {}
        node.resolution = ctx.get("resolution") or pred.model_name.rsplit("_", 1)[-1]
        node._bundle_metadata = {
            "default_threshold": 0.005,
            "path_label_horizon_bars": 16,
            "label_mean": [0.007, 0.007, 0.002, 1.5, 0.002, 0.05, 0.2],
            "label_std": [0.008, 0.008, 0.001, 1.0, 0.001, 0.1, 0.5],
        }

    async def _get_predictions(request: Any) -> MCPModelResponse:
        return MCPModelResponse(
            request_id=request.request_id,
            predictions=predictions,
            consensus_prediction=1.0,
            consensus_confidence=0.75,
            healthy_models=sum(
                1 for p in predictions if str(p.health_status).lower() == "healthy"
            ),
            total_models=len(predictions),
            timestamp=datetime.now(timezone.utc),
        )

    registry.get_predictions = AsyncMock(side_effect=_get_predictions)
    registry.get_model = lambda name: registry.models.get(name)
    return registry


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _ohlcv_df()
    frames = (df, df, df, df, df, df, df, df)
    monkeypatch.setattr(
        "agent.core.transformer_decision.fetch_mtf_market_frames",
        AsyncMock(return_value=frames),
    )
    monkeypatch.setattr(
        "agent.core.contract_state.get_contract_state",
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


@pytest.mark.asyncio
async def test_synth_is_default_decision_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [_prediction(r) for r in ("5m", "15m", "30m", "1h", "2h")]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["market_context"]["decision_path"] == "transformer_agent_synthesis"
    assert "market_state" in result["market_context"]


@pytest.mark.asyncio
async def test_synth_aligned_long_produces_buy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [
        _prediction("5m", mfe=0.02, mae=0.005),
        _prediction("15m", mfe=0.022, mae=0.005),
        _prediction("30m", mfe=0.02, mae=0.005),
        _prediction("1h", mfe=0.018, mae=0.006),
        _prediction("2h", mfe=0.017, mae=0.006),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["market_context"]["decision_path"] == "transformer_agent_synthesis"
    assert result["decision"]["signal"] in ("BUY", "STRONG_BUY")
    ms = result["market_context"]["market_state"]
    assert ms["thesis"] == "long"
    assert ms["climate"] == "long"
    plan = result["market_context"]["execution_plan"]
    assert plan.get("primary_tf") == "tf_15m"
    assert "stop_loss_pct" in plan


@pytest.mark.asyncio
async def test_synth_5m_only_hot_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [
        _prediction("5m", mfe=0.025, mae=0.004),
        _prediction("15m", mfe=0.007, mae=0.007),
        _prediction("30m", mfe=0.007, mae=0.007),
        _prediction("1h", mfe=0.008, mae=0.008),
        _prediction("2h", mfe=0.008, mae=0.008),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["decision"]["signal"] == "HOLD"
    assert result["market_context"]["execution_plan"] == {}
    ms = result["market_context"]["market_state"]
    assert ms["setup"] == "flat" or ms["climate"] == "two_sided"


@pytest.mark.asyncio
async def test_synth_crisis_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [
        _prediction("5m", mfe=0.02, mae=0.005),
        _prediction("15m", mfe=0.022, mae=0.005),
        _prediction("30m", mfe=0.02, mae=0.005),
        _prediction("1h", mfe=0.018, mae=0.006, vol_regime="EXTREME"),
        _prediction("2h", mfe=0.017, mae=0.006),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["decision"]["signal"] == "HOLD"
    codes = result["market_context"].get("transformer_reason_codes") or []
    assert any("crisis" in c for c in codes)


@pytest.mark.asyncio
async def test_synth_timing_against_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [
        _prediction("5m", mfe=0.004, mae=0.02),
        _prediction("15m", mfe=0.022, mae=0.005),
        _prediction("30m", mfe=0.02, mae=0.005),
        _prediction("1h", mfe=0.018, mae=0.006),
        _prediction("2h", mfe=0.017, mae=0.006),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["decision"]["signal"] == "HOLD"
    ms = result["market_context"]["market_state"]
    assert ms["timing"] == "against"


@pytest.mark.asyncio
async def test_synth_30m_opposed_not_strong(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [
        _prediction("5m", mfe=0.02, mae=0.005),
        _prediction("15m", mfe=0.022, mae=0.005),
        _prediction("30m", mfe=0.005, mae=0.02),
        _prediction("1h", mfe=0.018, mae=0.006),
        _prediction("2h", mfe=0.017, mae=0.006),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["decision"]["signal"] == "BUY"
    codes = result["market_context"].get("transformer_reason_codes") or []
    assert "setup_30m_opposed_cap" in codes


@pytest.mark.asyncio
async def test_synth_hold_keeps_15m_path_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    preds = [
        _prediction("5m", mfe=0.007, mae=0.007),
        _prediction("15m", mfe=0.009, mae=0.006),
        _prediction("30m", mfe=0.008, mae=0.007),
        _prediction("1h", mfe=0.008, mae=0.0075, vol_regime="LOW"),
        _prediction("2h", mfe=0.0085, mae=0.007, vol_regime="LOW"),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(preds),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )
    assert result["decision"]["signal"] == "HOLD"
    ms = result["market_context"]["market_state"]
    assert ms["path_edge"] == pytest.approx(0.003)
    assert ms["climate"] == "two_sided"
