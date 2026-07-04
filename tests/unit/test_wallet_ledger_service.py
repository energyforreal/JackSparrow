"""Tests for WalletLedgerService sync orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.wallet_ledger_service import WalletLedgerService, reset_wallet_ledger_service_for_tests


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_wallet_ledger_service_for_tests()
    yield
    reset_wallet_ledger_service_for_tests()


@pytest.fixture
def wallet_settings(monkeypatch):
    monkeypatch.setattr(
        "agent.core.wallet_ledger_service.settings",
        MagicMock(
            wallet_ledger_sync_enabled=True,
            database_url="postgresql://user:pass@localhost/test",
            wallet_ledger_default_transaction_types="commission,funding",
            wallet_ledger_fill_sync_debounce_seconds=1,
        ),
    )


@pytest.mark.asyncio
async def test_sync_incremental_paginates_and_updates_checkpoint(wallet_settings):
    client = MagicMock()
    client.get_wallet_transactions = AsyncMock(
        side_effect=[
            {
                "success": True,
                "result": [
                    {
                        "id": 1,
                        "amount": "-0.1",
                        "balance": "9.9",
                        "transaction_type": "commission",
                        "meta_data": {"order_id": 100},
                        "product_id": 27,
                        "asset_symbol": "BTC",
                        "created_at": "2026-07-04T10:30:00.000Z",
                    }
                ],
                "meta": {"after": "cursor_page2"},
            },
            {
                "success": True,
                "result": [],
                "meta": {"after": None},
            },
        ]
    )
    service = WalletLedgerService(client)
    with patch(
        "agent.core.wallet_ledger_service.load_wallet_sync_state_async",
        AsyncMock(return_value=None),
    ), patch(
        "agent.core.wallet_ledger_service.persist_wallet_transactions_batch_async",
        AsyncMock(return_value=1),
    ) as mock_persist, patch(
        "agent.core.wallet_ledger_service.update_wallet_sync_state_async",
        AsyncMock(),
    ) as mock_checkpoint:
        result = await service.sync_incremental(reason="test")
    assert result["success"] is True
    assert result["rows_synced"] == 1
    assert client.get_wallet_transactions.await_count == 2
    mock_persist.assert_awaited()
    mock_checkpoint.assert_awaited()
    checkpoint_kwargs = mock_checkpoint.await_args.kwargs
    assert checkpoint_kwargs.get("last_error") is None


@pytest.mark.asyncio
async def test_sync_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "agent.core.wallet_ledger_service.settings",
        MagicMock(wallet_ledger_sync_enabled=False),
    )
    service = WalletLedgerService(MagicMock())
    result = await service.sync_incremental()
    assert result.get("skipped") is True
