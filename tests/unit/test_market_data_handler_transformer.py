"""Unit tests for transformer-compatible market data pipeline triggers."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.events.handlers.market_data_handler import MarketDataEventHandler
from agent.events.schemas import FeatureRequestEvent, ModelPredictionRequestEvent
from agent.models.mcp_model_registry import MCPModelRegistry


def _transformer_registry() -> MCPModelRegistry:
    registry = MCPModelRegistry()
    model = MagicMock()
    model.model_name = "jacksparrow_transformer_BTCUSD_15m"
    model.model_type = "transformer"
    model.get_model_info.return_value = {
        "features_required": ["ret_1", "rv_16", "rsi_14"],
    }
    registry.register_model(model)
    return registry


def _legacy_registry() -> MCPModelRegistry:
    registry = MCPModelRegistry()
    model = MagicMock()
    model.model_name = "legacy_model"
    model.model_type = "xgboost"
    model.get_model_info.return_value = {
        "features_required": ["rsi_14", "macd_histogram"],
    }
    registry.register_model(model)
    return registry


def test_uses_transformer_internal_features() -> None:
    registry = _transformer_registry()
    assert registry.uses_transformer_internal_features() is True
    assert registry.get_mcp_servable_feature_names() == []


def test_mixed_registry_not_transformer_internal() -> None:
    registry = _transformer_registry()
    legacy = MagicMock()
    legacy.model_name = "legacy"
    legacy.model_type = "xgboost"
    legacy.get_model_info.return_value = {"features_required": ["rsi_14"]}
    registry.register_model(legacy)
    assert registry.uses_transformer_internal_features() is False
    names = registry.get_mcp_servable_feature_names()
    assert "rsi_14" in names


def test_get_runtime_feature_names_empty_for_transformer() -> None:
    orchestrator = SimpleNamespace(model_registry=_transformer_registry())
    with patch(
        "agent.events.handlers.market_data_handler.MarketDataEventHandler._get_model_registry",
        return_value=orchestrator.model_registry,
    ):
        assert MarketDataEventHandler._get_runtime_feature_names() == []


@pytest.mark.asyncio
async def test_emit_decision_pipeline_transformer_direct() -> None:
    orchestrator = SimpleNamespace(model_registry=_transformer_registry())
    with patch(
        "agent.events.handlers.market_data_handler.MarketDataEventHandler._get_model_registry",
        return_value=orchestrator.model_registry,
    ):
        with patch(
            "agent.events.handlers.market_data_handler.event_bus.publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            event_id = await MarketDataEventHandler.emit_decision_pipeline_trigger(
                symbol="BTCUSD",
                current_price=62000.0,
                trigger="candle_closed",
                correlation_id="corr-1",
                timestamp=datetime.now(timezone.utc),
                extra_context={"interval": "5m"},
            )
            mock_publish.assert_awaited_once()
            published = mock_publish.await_args.args[0]
            assert isinstance(published, ModelPredictionRequestEvent)
            assert published.payload["symbol"] == "BTCUSD"
            assert published.payload["features"] == {}
            assert published.payload["context"]["trigger"] == "candle_closed"
            assert event_id == published.event_id


@pytest.mark.asyncio
async def test_emit_decision_pipeline_feature_request_for_legacy() -> None:
    orchestrator = SimpleNamespace(model_registry=_legacy_registry())
    with patch(
        "agent.events.handlers.market_data_handler.MarketDataEventHandler._get_model_registry",
        return_value=orchestrator.model_registry,
    ):
        with patch(
            "agent.events.handlers.market_data_handler.event_bus.publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            await MarketDataEventHandler.emit_decision_pipeline_trigger(
                symbol="BTCUSD",
                current_price=62000.0,
                trigger="price_fluctuation",
            )
            mock_publish.assert_awaited_once()
            published = mock_publish.await_args.args[0]
            assert isinstance(published, FeatureRequestEvent)
            assert "rsi_14" in published.payload["feature_names"]


@pytest.mark.asyncio
async def test_handle_candle_closed_transformer_bypass() -> None:
    handler = MarketDataEventHandler()
    orchestrator = SimpleNamespace(model_registry=_transformer_registry())
    event = MagicMock()
    event.event_id = "evt-1"
    event.payload = {
        "symbol": "BTCUSD",
        "interval": "5m",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 100.0,
        "timestamp": datetime.now(timezone.utc),
    }
    with patch(
        "agent.events.handlers.market_data_handler.MarketDataEventHandler._get_model_registry",
        return_value=orchestrator.model_registry,
    ):
        with patch(
            "agent.events.handlers.market_data_handler.event_bus.publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            with patch.object(handler.context_manager, "update_state", new_callable=AsyncMock):
                await handler.handle_candle_closed(event)
                published = mock_publish.await_args.args[0]
                assert isinstance(published, ModelPredictionRequestEvent)
