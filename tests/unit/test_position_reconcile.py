"""Unit tests for exchange ↔ local position reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.position_reconcile import (
    exchange_open_symbols,
    parse_margined_rows,
    symbols_to_monitor,
)


def test_parse_margined_rows_list():
    view = {"success": True, "result": [{"product_symbol": "BTCUSD", "size": 1}]}
    rows = parse_margined_rows(view)
    assert len(rows) == 1
    assert rows[0]["product_symbol"] == "BTCUSD"


def test_exchange_open_symbols_filters_zero_size():
    rows = [
        {"product_symbol": "BTCUSD", "size": 2, "entry_price": "78000"},
        {"product_symbol": "ETHUSD", "size": 0},
    ]
    out = exchange_open_symbols(rows)
    assert list(out.keys()) == ["BTCUSD"]
    assert out["BTCUSD"]["size"] == 2


def test_symbols_to_monitor_only_local_open():
    pm = MagicMock()
    pm.get_all_positions.return_value = {
        "BTCUSD": {"status": "open", "symbol": "BTCUSD"},
        "ETHUSD": {"status": "closed", "symbol": "ETHUSD"},
    }
    execution = MagicMock()
    execution.position_manager = pm
    assert symbols_to_monitor(execution) == ["BTCUSD"]


@pytest.mark.asyncio
async def test_reconcile_adopts_missing_local_when_attributed():
    from agent.core.position_reconcile import reconcile_positions_with_exchange
    from unittest.mock import patch

    pm = MagicMock()
    pm.get_all_positions.return_value = {}
    pm.get_position.return_value = None

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
                    "created_at": "2026-05-16T20:02:00.233221Z",
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


@pytest.mark.asyncio
async def test_reconcile_clears_stale_local():
    from agent.core.position_reconcile import reconcile_positions_with_exchange

    pm = MagicMock()
    pm.get_all_positions.return_value = {
        "BTCUSD": {"status": "open", "entry_price": 78000, "current_price": 78100},
    }
    pm.get_position.return_value = {"status": "open"}
    pm.close_position.return_value = {}

    execution = MagicMock()
    execution.position_manager = pm
    execution.get_margined_positions_view = AsyncMock(
        return_value={"success": True, "result": []}
    )
    execution.adopt_exchange_position = AsyncMock()
    execution.close_exchange_position = AsyncMock()

    summary = await reconcile_positions_with_exchange(execution)
    assert summary["cleared_local"] == ["BTCUSD"]
    pm.close_position.assert_called_once()
