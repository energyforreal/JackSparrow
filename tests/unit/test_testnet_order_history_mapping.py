"""Unit tests for Delta order-history → closed-trade row mapping."""

from decimal import Decimal

from backend.services.testnet_portfolio_service import _map_order_history_row


def test_map_order_history_row_uses_created_and_updated_for_duration():
    row = {
        "id": 42,
        "product_symbol": "BTCUSD",
        "side": "buy",
        "size": 1,
        "average_fill_price": 79000.0,
        "created_at": "2026-05-16T10:00:00Z",
        "updated_at": "2026-05-16T10:00:03Z",
        "realized_pnl": 0,
    }
    mapped = _map_order_history_row(row, Decimal("83"))
    assert mapped["duration_seconds"] == 3
    assert mapped["entry_price"] == 79000.0
    assert mapped["exit_price"] == 79000.0
