"""Unit tests for Delta fill → Recent Trades mapping and merge."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
os.environ.setdefault("TRADING_MODE", "testnet")

from agent.data.delta_client import DeltaExchangeClient
from backend.api.models.responses import ClosedTradeResponse
from backend.services.portfolio_fetch import merge_recent_trades
from backend.services.testnet_portfolio_service import (
    _collect_agent_order_ids,
    _map_delta_fill_row,
    _order_row_is_agent,
    _parse_fill_timestamp,
)


def test_parse_fill_timestamp_microseconds():
    ts_us = 1725865015000000
    dt = _parse_fill_timestamp(ts_us)
    assert dt.year == 2024
    assert dt.tzinfo is not None


def test_delta_client_parse_fill_timestamp_static():
    dt = DeltaExchangeClient.parse_fill_timestamp("1725865015000000")
    assert dt is not None
    assert dt.tzinfo is not None


def test_order_row_is_agent_js_prefix():
    assert _order_row_is_agent({"client_order_id": "js_abc123", "id": 1})
    assert not _order_row_is_agent({"client_order_id": "manual_1", "id": 2})


def test_collect_agent_order_ids():
    history = {
        "result": [
            {"id": 100, "client_order_id": "js_entry"},
            {"id": 200, "client_order_id": "manual"},
        ]
    }
    ids = _collect_agent_order_ids(history)
    assert ids == {"100"}


def test_map_delta_fill_row():
    row = _map_delta_fill_row(
        {
            "id": 112233,
            "size": 5,
            "fill_type": "normal",
            "side": "buy",
            "price": "67200",
            "role": "taker",
            "commission": "0.0018",
            "created_at": 1725865015000000,
            "product_id": 27,
            "product_symbol": "BTCUSD",
            "order_id": "123456",
            "meta_data": {"order_type": "limit_order"},
        }
    )
    assert row["trade_id"] == "fill_112233"
    assert row["fill_id"] == "112233"
    assert row["exchange_order_id"] == "123456"
    assert row["record_kind"] == "fill"
    assert row["data_source"] == "exchange_fill"
    assert row["status"] == "FILLED"
    assert row["role"] == "taker"
    assert float(row["commission_usd"]) == pytest.approx(0.0018, rel=1e-6)
    assert row["fill_type"] == "normal"
    assert row["order_type"] == "limit_order"
    assert row["entry_time"] is None

    validated = ClosedTradeResponse(**row)
    assert validated.trade_id == "fill_112233"


def test_merge_recent_trades_dedupes_and_sorts():
    ledger = [
        {
            "trade_id": "agent_pos_1",
            "position_id": "pos_1",
            "symbol": "BTCUSD",
            "side": "LONG",
            "quantity": 1,
            "entry_price": 100.0,
            "exit_price": 110.0,
            "pnl": 0,
            "pnl_usd": 0,
            "status": "CLOSED",
            "entry_time": datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            "exit_time": datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
            "duration_seconds": 3600,
            "executed_at": datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
        }
    ]
    fills = [
        {
            "trade_id": "fill_99",
            "position_id": "",
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1,
            "exit_price": 105.0,
            "pnl": 0,
            "pnl_usd": 0,
            "status": "FILLED",
            "executed_at": datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
            "exit_time": datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
            "record_kind": "fill",
        }
    ]
    merged = merge_recent_trades(ledger, fills, limit=10)
    assert len(merged) == 2
    assert merged[0]["trade_id"] == "fill_99"
    assert merged[1]["trade_id"] == "agent_pos_1"
