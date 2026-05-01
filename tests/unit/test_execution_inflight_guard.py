"""Execution engine should reject concurrent same-symbol opens."""

import asyncio

import pytest

from agent.core.execution import ExecutionEngine


@pytest.mark.asyncio
async def test_execute_trade_blocks_concurrent_same_symbol():
    engine = ExecutionEngine()
    engine._initialized = True
    engine.exchange_connected = True

    async def fake_validate(_trade):
        return {"valid": True}

    async def fake_place_order(symbol, side, quantity, order_type, price=None):
        await asyncio.sleep(0.05)
        return {
            "success": True,
            "order_id": "ord_1",
            "filled_immediately": True,
            "average_fill_price": 50000.0,
        }

    engine._validate_trade = fake_validate  # type: ignore[assignment]
    engine._place_order = fake_place_order  # type: ignore[assignment]
    engine._place_stop_order = lambda *args, **kwargs: asyncio.sleep(0)  # type: ignore[assignment]
    engine._place_limit_order = lambda *args, **kwargs: asyncio.sleep(0)  # type: ignore[assignment]

    trade = {
        "symbol": "BTCUSD",
        "side": "buy",
        "quantity": 1.0,
        "order_type": "market",
        "price": 50000.0,
        "stop_loss": None,
        "take_profit": None,
    }

    first, second = await asyncio.gather(
        engine.execute_trade(dict(trade)),
        engine.execute_trade(dict(trade)),
    )

    messages = [first.error_message or "", second.error_message or ""]
    assert first.success != second.success
    assert any("Trade already in progress for BTCUSD" in msg for msg in messages)
