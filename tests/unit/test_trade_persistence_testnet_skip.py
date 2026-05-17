"""Trade persistence is skipped in testnet mode (exchange is ledger)."""

import pytest

from backend.services.trade_persistence_service import trade_persistence_service


@pytest.mark.asyncio
async def test_create_trade_and_position_skipped_in_testnet(monkeypatch):
    monkeypatch.setattr(
        "backend.services.trade_persistence_service.is_testnet_trading_mode",
        lambda: True,
    )
    result = await trade_persistence_service.create_trade_and_position(
        trade_id="t1",
        symbol="BTCUSD",
        side="BUY",
        quantity=1.0,
        fill_price=79000.0,
    )
    assert result.get("skipped") is True
    assert result.get("reason") == "testnet_exchange_ledger"


@pytest.mark.asyncio
async def test_close_position_skipped_in_testnet(monkeypatch):
    monkeypatch.setattr(
        "backend.services.trade_persistence_service.is_testnet_trading_mode",
        lambda: True,
    )
    result = await trade_persistence_service.close_position(
        position_id="ex_1",
        exit_price=80000.0,
        exit_reason="stop_loss",
        pnl=100.0,
        symbol="BTCUSD",
    )
    assert result.get("skipped") is True
    assert result.get("reason") == "testnet_exchange_ledger"
