"""Unit tests for exchange ↔ local position reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.position_reconcile import (
    _enrich_payload_from_fills,
    _fill_is_closing_leg,
    _infer_bracket_exit_reason,
    _resolve_exit_from_closing_fill,
    exchange_open_symbols,
    maybe_handle_exchange_bracket_flat_exit,
    notify_exchange_flat_position_closed,
    parse_margined_rows,
    reconcile_positions_with_exchange,
    symbols_to_monitor,
)
from agent.events.schemas import PositionClosedEvent


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


def test_infer_bracket_exit_reason_stop_loss_long():
    pos = {"side": "long", "stop_loss": 77000.0, "take_profit": 80000.0}
    assert _infer_bracket_exit_reason(pos, 77000.0) == "stop_loss_hit"


def test_infer_bracket_exit_reason_take_profit_long():
    pos = {"side": "long", "stop_loss": 77000.0, "take_profit": 80000.0}
    assert _infer_bracket_exit_reason(pos, 80000.0) == "take_profit_hit"


def test_fill_is_closing_leg_short_reduce_only():
    pos = {"side": "short"}
    row = {"side": "buy", "meta_data": {"reduce_only": True}}
    assert _fill_is_closing_leg(row, pos) is True


def test_fill_is_closing_leg_long_opposite_side():
    pos = {"side": "long"}
    row = {"side": "sell"}
    assert _fill_is_closing_leg(row, pos) is True


@pytest.mark.asyncio
async def test_resolve_exit_from_closing_fill_prefers_reduce_only():
    execution = MagicMock()
    execution.delta_client = MagicMock()
    execution.delta_client.resolve_product_id = AsyncMock(return_value=84)
    execution.delta_client.get_fills = AsyncMock(
        return_value={
            "result": [
                {
                    "product_symbol": "BTCUSD",
                    "price": "71093.2",
                    "created_at": 1000,
                    "side": "buy",
                },
                {
                    "product_symbol": "BTCUSD",
                    "price": "76000.0",
                    "created_at": 2000,
                    "side": "buy",
                    "meta_data": {"reduce_only": True},
                },
            ]
        }
    )

    pos = {
        "side": "short",
        "entry_price": 71093.2,
        "opened_at": "2026-06-01T20:00:00+00:00",
    }
    resolved = await _resolve_exit_from_closing_fill(execution, "BTCUSD", pos)

    assert resolved is not None
    assert resolved["exit_price"] == 76000.0
    assert resolved["source"] == "closing_fill"


@pytest.mark.asyncio
async def test_notify_exchange_flat_uses_same_exit_for_close_and_event():
    pm = MagicMock()
    pos = {
        "status": "open",
        "entry_price": 71093.2,
        "current_price": 71093.2,
        "side": "short",
        "lots": 1,
        "opened_at": "2026-06-01T20:00:00+00:00",
    }
    pm.get_position.return_value = pos
    pm.close_position.return_value = {"entry_order_id": "ord_1"}

    execution = MagicMock()
    execution.position_manager = pm
    execution.delta_client = MagicMock()
    execution.delta_client.resolve_product_id = AsyncMock(return_value=84)
    execution.delta_client.get_fills = AsyncMock(
        return_value={
            "result": [
                {
                    "product_symbol": "BTCUSD",
                    "price": "76000.0",
                    "created_at": 2000,
                    "side": "buy",
                    "meta_data": {"reduce_only": True},
                }
            ]
        }
    )

    with patch("agent.core.position_reconcile.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        with patch("agent.core.position_reconcile.settings") as mock_settings:
            mock_settings.contract_value_btc = 0.001
            mock_settings.taker_fee_rate = 0.0005
            mock_settings.slippage_bps = 5.0
            published = await notify_exchange_flat_position_closed(
                execution,
                "BTCUSD",
                pos,
                source="position_reconcile",
            )

    assert published is True
    pm.close_position.assert_called_once()
    close_kwargs = pm.close_position.call_args.kwargs
    assert close_kwargs["exit_price"] == 76000.0

    event = mock_publish.await_args[0][0]
    assert event.payload["exit_price"] == 76000.0


@pytest.mark.asyncio
async def test_enrich_payload_skips_when_exit_already_resolved():
    execution = MagicMock()
    payload = {"exit_price": 76000.0, "exit_price_resolved_from_fill": True, "side": "short"}

    await _enrich_payload_from_fills(
        execution,
        "BTCUSD",
        payload,
        pos={"side": "short"},
        skip_if_resolved=True,
    )

    execution.delta_client.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_adopts_missing_local_when_attributed():
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
            mock_settings.block_entries_on_reconcile_divergence = True
            summary = await reconcile_positions_with_exchange(execution)

    assert summary["adopted"] == ["BTCUSD"]
    execution.adopt_exchange_position.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_clears_stale_local_and_publishes_event():
    pm = MagicMock()
    pm.get_all_positions.return_value = {
        "BTCUSD": {
            "status": "open",
            "entry_price": 78000,
            "current_price": 78100,
            "side": "long",
            "lots": 1,
        },
    }
    pm.get_position.return_value = {
        "status": "open",
        "entry_price": 78000,
        "current_price": 78100,
        "side": "long",
        "lots": 1,
    }
    pm.close_position.return_value = {"entry_order_id": "ord_1"}

    execution = MagicMock()
    execution.position_manager = pm
    execution.delta_client = None
    execution.get_margined_positions_view = AsyncMock(
        return_value={"success": True, "result": []}
    )
    execution.adopt_exchange_position = AsyncMock()
    execution.close_exchange_position = AsyncMock()

    with patch("agent.core.position_reconcile.event_bus.publish", new_callable=AsyncMock) as mock_publish:
        with patch("agent.core.position_reconcile.settings") as mock_settings:
            mock_settings.exchange_position_reconcile_enabled = True
            mock_settings.agent_only_delta_orders = True
            mock_settings.exchange_position_reconcile_orphan_mode = "close_orphan"
            mock_settings.block_entries_on_reconcile_divergence = True
            mock_settings.contract_value_btc = 0.001
            mock_settings.taker_fee_rate = 0.0005
            mock_settings.slippage_bps = 5.0
            summary = await reconcile_positions_with_exchange(execution)

    assert summary["cleared_local"] == ["BTCUSD"]
    pm.close_position.assert_called_once()
    mock_publish.assert_awaited_once()
    published = mock_publish.await_args[0][0]
    assert isinstance(published, PositionClosedEvent)
    assert published.payload["symbol"] == "BTCUSD"
    assert "reconcile" in published.payload["exit_reason"] or published.payload["exit_reason"] in (
        "stop_loss_hit",
        "take_profit_hit",
        "exchange_bracket_exit",
    )


@pytest.mark.asyncio
async def test_maybe_handle_exchange_bracket_flat_exit_when_flat():
    pm = MagicMock()
    pm.get_all_positions.return_value = {
        "BTCUSD": {
            "status": "open",
            "entry_price": 78000,
            "current_price": 77900,
            "side": "long",
            "lots": 1,
            "stop_loss": 77000,
            "take_profit": 80000,
        },
    }
    pm.get_position.return_value = pm.get_all_positions.return_value["BTCUSD"]
    pm.close_position.return_value = {}

    execution = MagicMock()
    execution.position_manager = pm
    execution.delta_client = None
    execution.get_margined_positions_view = AsyncMock(
        return_value={"success": True, "result": []}
    )

    position = {
        "status": "open",
        "entry_price": 78000,
        "current_price": 77900,
        "side": "long",
        "lots": 1,
        "exchange_bracket_sl_tp": True,
        "bracket_order_id": 99,
    }

    with patch("agent.core.position_reconcile.event_bus.publish", new_callable=AsyncMock):
        with patch("agent.core.position_reconcile.settings") as mock_settings:
            mock_settings.bracket_exit_poll_enabled = True
            mock_settings.contract_value_btc = 0.001
            mock_settings.taker_fee_rate = 0.0005
            mock_settings.slippage_bps = 5.0
            result = await maybe_handle_exchange_bracket_flat_exit(
                execution, "BTCUSD", position
            )

    assert result is not None
    assert result["position_status"] == "closed"
    assert result["action"] == "exchange_bracket_closed"
    pm.close_position.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_handle_exchange_bracket_flat_exit_skips_when_exchange_open():
    execution = MagicMock()
    execution.get_margined_positions_view = AsyncMock(
        return_value={
            "success": True,
            "result": [{"product_symbol": "BTCUSD", "size": 1}],
        }
    )
    position = {"status": "open", "exchange_bracket_sl_tp": True}

    with patch("agent.core.position_reconcile.settings") as mock_settings:
        mock_settings.bracket_exit_poll_enabled = True
        result = await maybe_handle_exchange_bracket_flat_exit(
            execution, "BTCUSD", position
        )

    assert result is None
