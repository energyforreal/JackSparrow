"""Unit tests for Delta-compatible paper exchange gateway."""

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")

from agent.core.exchange_gateway import DeltaPaperSimExchangeGateway


def _position(
    symbol: str = "BTCUSD",
    side: str = "long",
    lots: float = 2.0,
    entry_price: float = 50_000.0,
    current_price: float = 50_100.0,
) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "lots": lots,
        "entry_price": entry_price,
        "current_price": current_price,
        "unrealized_pnl": 2.0,
        "entry_time": datetime.now(timezone.utc),
        "status": "open",
        "contract_value_btc": 0.001,
    }


@pytest.mark.asyncio
async def test_paper_gateway_positions_have_signed_size_and_margin():
    positions = {"BTCUSD": _position(side="short", lots=3.0)}

    async def _close(_symbol: str):
        raise AssertionError("close callback should not be called")

    gateway = DeltaPaperSimExchangeGateway(
        position_reader=lambda: positions,
        close_position_cb=_close,
        margined_view_delay_seconds=0.0,
    )

    out = await gateway.get_positions()
    assert out["success"] is True
    assert len(out["result"]) == 1
    row = out["result"][0]
    assert row["product_symbol"] == "BTCUSD"
    assert row["size"] == pytest.approx(-3.0)
    assert row["margin"] > 0
    assert "liquidation_price" in row


@pytest.mark.asyncio
async def test_margined_positions_can_lag_realtime_positions():
    positions = {"BTCUSD": _position(entry_price=50_000.0)}

    async def _close(_symbol: str):
        return type("R", (), {"success": True})()

    gateway = DeltaPaperSimExchangeGateway(
        position_reader=lambda: positions,
        close_position_cb=_close,
        margined_view_delay_seconds=60.0,
    )

    first = await gateway.get_margined_positions()
    first_entry = float(first["result"][0]["entry_price"])
    positions["BTCUSD"]["entry_price"] = 51_000.0
    latest = await gateway.get_positions()
    latest_entry = float(latest["result"][0]["entry_price"])
    second = await gateway.get_margined_positions()
    second_entry = float(second["result"][0]["entry_price"])

    assert latest_entry == pytest.approx(51_000.0)
    assert first_entry == pytest.approx(50_000.0)
    assert second_entry == pytest.approx(50_000.0)


@pytest.mark.asyncio
async def test_change_margin_and_close_all_behave_like_private_actions():
    positions = {"BTCUSD": _position(), "ETHUSD": _position(symbol="ETHUSD")}
    closed: list[str] = []

    async def _close(symbol: str):
        closed.append(symbol)
        positions.pop(symbol, None)
        return type("R", (), {"success": True})()

    gateway = DeltaPaperSimExchangeGateway(
        position_reader=lambda: positions,
        close_position_cb=_close,
        margined_view_delay_seconds=0.0,
    )

    before = await gateway.get_positions(symbol="BTCUSD")
    before_margin = float(before["result"][0]["margin"])
    changed = await gateway.change_margin("BTCUSD", margin=25.0)
    assert changed["success"] is True
    assert float(changed["result"]["margin"]) == pytest.approx(before_margin + 25.0)

    close_all = await gateway.close_all_positions()
    assert close_all["success"] is True
    assert set(close_all["result"]["closed_symbols"]) == {"BTCUSD", "ETHUSD"}
    assert positions == {}
