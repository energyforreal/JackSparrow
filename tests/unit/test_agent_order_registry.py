"""Unit tests for agent-only Delta order attribution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.agent_order_registry import (
    AGENT_DECISION_AUTHORITY,
    clear_registry,
    is_agent_controlled_authority,
    is_exchange_position_agent_attributed,
    record_agent_order_fill,
    record_agent_order_intent,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_is_agent_controlled_authority():
    assert is_agent_controlled_authority(AGENT_DECISION_AUTHORITY)
    assert not is_agent_controlled_authority("manual_client")
    assert not is_agent_controlled_authority(None)


@pytest.mark.asyncio
async def test_registry_attribution_matches_recent_fill():
    record_agent_order_fill(
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        fill_price=78000.0,
        execution_authority=AGENT_DECISION_AUTHORITY,
        client_order_id="js_abc123",
    )
    execution = MagicMock()
    row = {"size": 1, "entry_price": "78000"}
    assert await is_exchange_position_agent_attributed(execution, "BTCUSD", row)


@pytest.mark.asyncio
async def test_unattributed_position_when_registry_empty():
    execution = MagicMock()
    execution.delta_client = None
    row = {"size": 1, "entry_price": "78000"}
    with patch("agent.core.agent_order_registry.settings") as mock_settings:
        mock_settings.agent_only_delta_orders = True
        assert not await is_exchange_position_agent_attributed(execution, "BTCUSD", row)


@pytest.mark.asyncio
async def test_execute_trade_rejects_manual_authority():
    from agent.core.execution import ExecutionEngine

    engine = ExecutionEngine()
    engine._initialized = True
    engine.exchange_connected = True

    with patch("agent.core.execution.settings") as mock_settings:
        mock_settings.agent_only_delta_orders = True
        mock_settings.block_manual_execute_trade = True
        result = await engine.execute_trade(
            {
                "symbol": "BTCUSD",
                "side": "buy",
                "quantity": 1,
                "execution_authority": "manual_client",
            }
        )
    assert not result.success
    assert "agent" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_reconcile_closes_unattributed_exchange_leg():
    from agent.core.position_reconcile import reconcile_positions_with_exchange

    pm = MagicMock()
    pm.get_all_positions.return_value = {}

    execution = MagicMock()
    execution.position_manager = pm
    execution.get_margined_positions_view = AsyncMock(
        return_value={
            "success": True,
            "result": [
                {
                    "product_symbol": "BTCUSD",
                    "size": 1,
                    "entry_price": "78000",
                }
            ],
        }
    )
    execution.adopt_exchange_position = AsyncMock(return_value=True)
    close_result = MagicMock(success=True)
    execution.close_exchange_position = AsyncMock(return_value=close_result)

    with patch(
        "agent.core.position_reconcile.is_exchange_position_agent_attributed",
        new=AsyncMock(return_value=False),
    ):
        with patch("agent.core.position_reconcile.settings") as mock_settings:
            mock_settings.exchange_position_reconcile_enabled = True
            mock_settings.agent_only_delta_orders = True
            mock_settings.exchange_position_reconcile_orphan_mode = "close_orphan"
            summary = await reconcile_positions_with_exchange(execution)

    assert summary["closed_exchange"] == ["BTCUSD"]
    execution.adopt_exchange_position.assert_not_awaited()
    execution.close_exchange_position.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_adopts_attributed_missing_local():
    from agent.core.position_reconcile import reconcile_positions_with_exchange

    pm = MagicMock()
    pm.get_all_positions.return_value = {}

    execution = MagicMock()
    execution.position_manager = pm
    execution.get_margined_positions_view = AsyncMock(
        return_value={
            "success": True,
            "result": [
                {
                    "product_symbol": "BTCUSD",
                    "size": 1,
                    "entry_price": "78000",
                }
            ],
        }
    )
    execution.adopt_exchange_position = AsyncMock(return_value=True)
    execution.close_exchange_position = AsyncMock()

    with patch(
        "agent.core.position_reconcile.is_exchange_position_agent_attributed",
        new=AsyncMock(return_value=True),
    ):
        with patch("agent.core.position_reconcile.settings") as mock_settings:
            mock_settings.exchange_position_reconcile_enabled = True
            mock_settings.agent_only_delta_orders = True
            mock_settings.exchange_position_reconcile_orphan_mode = "close_orphan"
            summary = await reconcile_positions_with_exchange(execution)

    assert summary["adopted"] == ["BTCUSD"]
    execution.adopt_exchange_position.assert_awaited_once()
