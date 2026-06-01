"""Tests for position reconcile health gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.position_reconcile import (
    _set_reconcile_health,
    detect_position_divergence,
    get_reconcile_block_reason,
    is_reconcile_healthy,
    reconcile_positions_with_exchange,
)


@pytest.fixture(autouse=True)
def reset_health():
    _set_reconcile_health(True)
    yield
    _set_reconcile_health(True)


def test_detect_local_without_exchange():
    pm = MagicMock()
    pm.get_all_positions.return_value = {
        "BTCUSD": {"status": "open", "side": "long", "lots": 1, "entry_price": 78000},
    }
    execution = MagicMock()
    execution.position_manager = pm
    issues = detect_position_divergence(execution, [])
    assert any("local OPEN" in i for i in issues)


@pytest.mark.asyncio
async def test_fetch_failed_sets_unhealthy():
    execution = MagicMock()
    execution.get_margined_positions_view = AsyncMock(side_effect=RuntimeError("network"))

    with patch("agent.core.position_reconcile.settings") as mock_settings:
        mock_settings.exchange_position_reconcile_enabled = True
        mock_settings.block_entries_on_reconcile_divergence = True
        await reconcile_positions_with_exchange(execution)

    assert not is_reconcile_healthy()
    assert "fetch failed" in get_reconcile_block_reason().lower()


@pytest.mark.asyncio
async def test_aligned_after_reconcile_sets_healthy():
    pm = MagicMock()
    pm.get_all_positions.return_value = {}
    execution = MagicMock()
    execution.position_manager = pm
    execution.get_margined_positions_view = AsyncMock(
        return_value={"success": True, "result": []}
    )
    execution.adopt_exchange_position = AsyncMock()
    execution.close_exchange_position = AsyncMock()

    with patch("agent.core.position_reconcile.settings") as mock_settings:
        mock_settings.exchange_position_reconcile_enabled = True
        mock_settings.block_entries_on_reconcile_divergence = True
        mock_settings.agent_only_delta_orders = True
        mock_settings.exchange_position_reconcile_orphan_mode = "close_orphan"
        await reconcile_positions_with_exchange(execution)

    assert is_reconcile_healthy()
