"""Tests for wallet transaction persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from agent.persistence.db_writes import _persist_wallet_transactions_batch_sync


def test_persist_wallet_batch_uses_on_conflict_do_nothing():
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    records = [
        {
            "exchange": "delta",
            "exchange_transaction_id": 100234,
            "transaction_type": "commission",
            "asset_symbol": "BTC",
            "product_id": 27,
            "order_id": 987654,
            "amount": Decimal("-0.25"),
            "balance_after": Decimal("1.23"),
            "occurred_at": datetime(2026, 7, 4, 10, 30, tzinfo=timezone.utc),
            "metadata": {"id": 100234},
        }
    ]

    with patch("agent.persistence.db_writes._get_engine", return_value=mock_engine):
        count = _persist_wallet_transactions_batch_sync("postgresql://test", records)

    assert count == 1
    executed_sql = mock_conn.execute.call_args[0][0].text
    assert "ON CONFLICT (exchange, exchange_transaction_id) DO NOTHING" in executed_sql
    mock_conn.commit.assert_called_once()
