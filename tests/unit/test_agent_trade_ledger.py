"""Agent trade ledger — agent-only closed trades for Recent Trades."""

import pytest

from backend.services.agent_trade_ledger_service import (
    build_closed_trade_from_position_event,
    get_agent_closed_trades,
    record_closed_trade,
    clear_agent_trade_ledger,
    AGENT_CLIENT_ORDER_PREFIX,
    is_agent_client_order_id,
)
from decimal import Decimal


@pytest.mark.asyncio
async def test_build_closed_trade_from_position_event_round_trip():
    payload = {
        "position_id": "pos_abc123",
        "symbol": "BTCUSD",
        "side": "long",
        "entry_price": 78000.0,
        "exit_price": 79000.0,
        "quantity": 2,
        "pnl": 15.5,
        "entry_time": "2026-05-16T10:00:00+00:00",
        "timestamp": "2026-05-16T10:15:00+00:00",
        "exit_reason": "take_profit",
    }
    row = await build_closed_trade_from_position_event(payload, usdinr_rate=Decimal("83"))
    assert row["trade_id"] == "agent_pos_abc123"
    assert row["side"] == "LONG"
    assert row["entry_price"] == 78000.0
    assert row["exit_price"] == 79000.0
    assert row["duration_seconds"] == 900
    assert row["data_source"] == "agent"
    assert row["pnl_usd"] == 15.5


@pytest.mark.asyncio
async def test_record_and_list_agent_trades(tmp_path, monkeypatch):
    ledger_file = tmp_path / "agent_closed_trades.jsonl"
    monkeypatch.setattr(
        "backend.services.agent_trade_ledger_service._LEDGER_FILE",
        ledger_file,
    )
    monkeypatch.setattr(
        "backend.services.agent_trade_ledger_service._redis_lpush_row",
        lambda row: False,
    )
    monkeypatch.setattr(
        "backend.services.agent_trade_ledger_service._redis_read_rows",
        lambda **kwargs: None,
    )

    await clear_agent_trade_ledger()
    await record_closed_trade(
        {
            "position_id": "pos_1",
            "symbol": "BTCUSD",
            "side": "long",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "quantity": 1,
            "pnl": 5.0,
            "entry_time": "2026-05-16T10:00:00+00:00",
            "timestamp": "2026-05-16T10:01:00+00:00",
        }
    )
    rows = await get_agent_closed_trades(limit=10)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == "agent_pos_1"


def test_client_order_id_prefix():
    assert is_agent_client_order_id("js_a1b2c3d4")
    assert not is_agent_client_order_id("manual_order")
