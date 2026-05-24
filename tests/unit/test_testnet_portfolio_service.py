"""Unit tests for testnet portfolio mapping."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
os.environ.setdefault("TRADING_MODE", "testnet")

from backend.services.testnet_portfolio_service import (
    TestnetPortfolioService,
    _wallet_totals_usd,
)


def test_wallet_totals_prefers_delta_inr_fields():
    wallet = {
        "meta": {"net_equity": "69.5248553"},
        "result": [
            {
                "asset_symbol": "USD",
                "balance": "69.5248553",
                "available_balance": "69.5248553",
                "balance_inr": "5909.6127005",
                "available_balance_inr": "5909.6127005",
            }
        ],
    }
    totals = _wallet_totals_usd(wallet)
    assert abs(totals["balance_usd"] - 69.5248553) < 0.0001
    assert abs(totals["balance_inr"] - 5909.6127005) < 0.01
    assert abs(totals["available_inr"] - 5909.6127005) < 0.01


@pytest.mark.asyncio
async def test_finalize_uses_delta_balance_inr_not_fallback_rate(monkeypatch):
    svc = TestnetPortfolioService()
    partial = {
        "total_value_usd": 69.5248553,
        "available_usd": 69.5248553,
        "margin_used_usd": 0.0,
        "total_unrealized_usd": 0.0,
        "balance_inr_exchange": 5909.6127005,
        "available_inr_exchange": 5909.6127005,
        "positions_list": [],
        "sync_status": "live",
    }

    async def _fallback_rate():
        return 86.0

    monkeypatch.setattr(
        "backend.services.testnet_portfolio_service.get_usdinr_rate",
        _fallback_rate,
    )
    summary = await svc._finalize_summary_inr(partial)
    assert abs(summary["total_value"] - 5909.6127005) < 0.01
    assert abs(summary["total_value_usd"] - 69.5248553) < 0.0001
    assert abs(summary["wallet_balance_usd"] - 69.5248553) < 0.0001
    assert abs(summary["usd_inr_rate"] - 85.0) < 0.15


@pytest.mark.asyncio
async def test_attach_agent_realized_pnl_sums_ledger(monkeypatch):
    svc = TestnetPortfolioService()
    summary = {"total_realized_pnl": 0.0}

    async def _fake_rows(**kwargs):
        return [
            {"pnl": -100.0, "pnl_usd": -1.0},
            {"pnl": 50.0, "pnl_usd": 0.5},
        ]

    monkeypatch.setattr(
        "backend.services.agent_trade_ledger_service.get_agent_closed_trades",
        _fake_rows,
    )
    out = await svc._attach_agent_realized_pnl(summary)
    assert out["total_realized_pnl"] == -50.0
    assert out["total_realized_pnl_usd"] == -0.5


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
