"""Integration test: synthetic 5-TF predictions through agent synthesis path."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, List
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
        health_status="healthy",
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
                "trend_strength": 1.5,
                "drawdown_before_mfe": 0.0,
                "future_oi_change_pct": 0.05,
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
        if "resolution" in ctx:
            node.resolution = ctx["resolution"]
        else:
            name = str(pred.model_name or "")
            node.resolution = name.rsplit("_", 1)[-1] if "_" in name else "15m"
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


def _patch_frames(monkeypatch: pytest.MonkeyPatch) -> None:
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
        AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"exposure_pct": 0.0})),
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


@pytest.mark.asyncio
async def test_synthesis_emits_multi_tf_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_frames(monkeypatch)
    predictions = [
        _prediction("5m"),
        _prediction("15m"),
        _prediction("30m"),
        _prediction("1h"),
        _prediction("2h"),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(predictions),
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
    assert mctx.get("decision_path") == "transformer_agent_synthesis"
    assert "market_state" in mctx
    plan = mctx.get("execution_plan") or {}
    assert isinstance(plan, dict)
    if result["decision"]["signal"] in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
        assert "stop_loss_pct" in plan
        assert "take_profit_pct" in plan
        assert "size_fraction" in plan
        assert "rr_soft_action" in plan
    assert result["decision"]["signal"] in (
        "BUY",
        "STRONG_BUY",
        "HOLD",
        "SELL",
        "STRONG_SELL",
    )


@pytest.mark.asyncio
async def test_synthesis_climate_fights_setup_forces_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long setup with short climate → HOLD (setup fights climate)."""
    _patch_frames(monkeypatch)
    predictions = [
        _prediction("5m", mfe=0.02, mae=0.005),
        _prediction("15m", mfe=0.02, mae=0.005),
        _prediction("30m", mfe=0.02, mae=0.005),
        _prediction("1h", mfe=0.005, mae=0.02),
        _prediction("2h", mfe=0.005, mae=0.02),
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(predictions),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {"model_name": p.model_name},
    )

    assert result["decision"]["signal"] == "HOLD"
    codes = result["market_context"].get("transformer_reason_codes") or []
    assert any(
        c in codes for c in ("setup_fights_climate", "climate_short", "climate_conflicted")
    ) or result["market_context"]["market_state"]["climate"] == "short"


@pytest.mark.asyncio
async def test_synthesis_skips_degraded_predictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhealthy TF predictions must not enter views."""
    _patch_frames(monkeypatch)
    degraded_2h = MCPModelPrediction(
        model_name="jacksparrow_transformer_BTCUSD_2h",
        model_version="v1",
        prediction=0.0,
        confidence=0.0,
        reasoning="Model error: Need at least 128 feature rows",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status="degraded",
        context={},
    )
    predictions = [
        _prediction("5m"),
        _prediction("15m"),
        _prediction("30m"),
        _prediction("1h"),
        degraded_2h,
    ]
    result = await evaluate_transformer_prediction(
        symbol="BTCUSD",
        context={},
        model_registry=_mock_registry(predictions),
        delta_client=MagicMock(),
        t0=0.0,
        serialize_prediction=lambda p: {
            "model_name": p.model_name,
            "health_status": p.health_status,
        },
    )

    multi = result["market_context"].get("multi_tf_predictions") or {}
    assert "tf_2h" not in multi
    assert result["market_context"]["decision_path"] == "transformer_agent_synthesis"
