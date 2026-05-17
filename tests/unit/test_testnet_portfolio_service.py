"""Unit tests for testnet portfolio mapping."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
os.environ.setdefault("TRADING_MODE", "testnet")

from backend.services.testnet_portfolio_service import TestnetPortfolioService


@pytest.mark.asyncio
async def test_build_summary_from_margined_and_wallet():
    svc = TestnetPortfolioService()
    snapshot = {
        "success": True,
        "margined_positions": {
            "success": True,
            "result": [
                {
                    "product_symbol": "BTCUSD",
                    "size": 2,
                    "entry_price": "50000",
                    "mark_price": "51000",
                    "margin": "200",
                    "liquidation_price": "40000",
                    "unrealized_pnl": "20",
                    "id": 99,
                }
            ],
        },
        "wallet_balances": {
            "success": True,
            "result": [
                {"asset_symbol": "USD", "balance": "1000", "available_balance": "800"},
            ],
        },
        "order_history": {"success": True, "result": []},
    }
    partial = svc.build_summary_from_snapshot(snapshot, sync_status="live")
    assert partial["sync_status"] == "live"
    assert len(partial["positions_list"]) == 1
    assert partial["positions_list"][0]["symbol"] == "BTCUSD"
    assert partial["positions_list"][0]["lots"] == 2
    assert partial["total_value_usd"] >= 800


def test_map_position_uses_exchange_created_at():
    svc = TestnetPortfolioService()
    created = datetime(2026, 5, 16, 12, 6, 52, tzinfo=timezone.utc)
    snapshot = {
        "margined_positions": {
            "result": [
                {
                    "product_symbol": "BTCUSD",
                    "size": 1,
                    "entry_price": "78000",
                    "mark_price": "78100",
                    "margin": "10",
                    "created_at": created.isoformat().replace("+00:00", "Z"),
                }
            ],
        },
        "wallet_balances": {"result": []},
    }
    partial = svc.build_summary_from_snapshot(snapshot)
    opened = partial["positions_list"][0]["opened_at"]
    assert opened.year == 2026
    assert opened.month == 5
    assert opened.day == 16
