"""Regression tests for model prediction context propagation (JackSparrow v43 path)."""

import os
import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

# Ensure project root is on path (for agent imports).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force-load local `agent` package in case another installed package shadows it.
agent_init = ROOT / "agent" / "__init__.py"
agent_spec = importlib.util.spec_from_file_location("agent", agent_init)
if agent_spec and agent_spec.loader:
    agent_module = importlib.util.module_from_spec(agent_spec)
    agent_module.__path__ = [str(ROOT / "agent")]
    sys.modules["agent"] = agent_module
    agent_spec.loader.exec_module(agent_module)

# Ensure settings can initialize in test environments.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

from agent.core.mcp_orchestrator import MCPOrchestrator
from agent.core.v43_contract_state import ContractStateSnapshot
from agent.models.mcp_model_node import MCPModelPrediction
from feature_store.jacksparrow_v43_contract import V43_LEGACY_CANONICAL_FEATURES


@pytest.mark.asyncio
async def test_process_prediction_request_preserves_model_context():
    """Per-model context (including exit_signal) is preserved in orchestrator output."""
    orchestrator = MCPOrchestrator()
    orchestrator._initialized = True
    orchestrator.delta_client = object()

    prediction = MCPModelPrediction(
        model_name="jacksparrow_BTCUSD_15m",
        model_version="4.0.0",
        prediction=0.4,
        confidence=0.8,
        reasoning="v43 ensemble 15m",
        features_used=["ema_9"],
        feature_importance={},
        computation_time_ms=12.5,
        health_status="healthy",
        context={
            "entry_signal": 0.4,
            "exit_signal": -0.6,
            "multi_horizon_heads": {
                "intraday_30m": {
                    "horizon_key": "intraday_30m",
                    "forward_bars": 6,
                    "expected_return": 0.012,
                    "threshold": 0.005,
                    "short_threshold": 0.005,
                    "regime": "neutral",
                },
            },
            "closed_bar_features": {"ret_1": 0.001, "atr_pct": 0.01},
        },
    )
    bundle_meta = {
        "model_family": "jacksparrow_v43_multihead",
        "features": list(V43_LEGACY_CANONICAL_FEATURES),
        "compatible_feature_version": "jacksparrow_v43_features_v1",
        "horizons": {
            "scalp_10m": {"forward_bars": 2, "validation_metrics": {"dynamic_threshold": 0.004}},
            "intraday_30m": {"forward_bars": 6, "validation_metrics": {"dynamic_threshold": 0.005}},
            "trend_1h": {"forward_bars": 12, "validation_metrics": {"dynamic_threshold": 0.006}},
            "swing_2h": {"forward_bars": 24, "validation_metrics": {"dynamic_threshold": 0.007}},
        },
    }
    mock_model = SimpleNamespace(_bundle_metadata=bundle_meta)
    model_response = SimpleNamespace(
        predictions=[prediction],
        consensus_prediction=0.4,
        consensus_confidence=0.8,
        healthy_models=1,
        total_models=1,
    )
    orchestrator.model_registry = SimpleNamespace(
        get_required_feature_names=lambda: ["ema_9"],
        get_predictions=AsyncMock(return_value=model_response),
        get_model=lambda _name: mock_model,
        models={"jacksparrow_BTCUSD_15m": mock_model},
    )

    reasoning_chain = SimpleNamespace(
        chain_id="chain-1",
        steps=[],
        conclusion="buy",
        final_confidence=0.81,
    )
    orchestrator.reasoning_engine = SimpleNamespace(
        generate_reasoning=AsyncMock(return_value=reasoning_chain)
    )

    df_stub = pd.DataFrame(
        {
            "close": [1.0, 2.0, 3.0],
            "timestamp": pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC"),
        }
    )
    contract_snap = ContractStateSnapshot(
        symbol="BTCUSD",
        state="live",
        trading_status="operational",
        only_reduce_only_orders_allowed=False,
        maintenance_margin=0.25,
        initial_margin=0.5,
        max_leverage_notional=100000.0,
        impact_size=10000.0,
        price_band_pct=2.5,
    )
    with patch(
        "agent.core.v43_market_frames.fetch_v43_market_frames",
        new_callable=AsyncMock,
        return_value=(df_stub, df_stub, df_stub, df_stub, pd.DataFrame(), pd.DataFrame()),
    ), patch(
        "agent.core.v43_contract_state.get_contract_state",
        new_callable=AsyncMock,
        return_value=contract_snap,
    ):
        result = await orchestrator.process_prediction_request("BTCUSD", {})

    top_level_ctx = result["model_predictions"][0]["context"]
    market_ctx = result["market_context"]["model_predictions"][0]["context"]
    model_ctx = result["models"]["predictions"][0]["context"]

    assert top_level_ctx["entry_signal"] == 0.4
    assert top_level_ctx["exit_signal"] == -0.6
    assert market_ctx == top_level_ctx
    assert model_ctx == top_level_ctx
