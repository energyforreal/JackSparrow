"""Recent closed trades fetch routes to testnet exchange in testnet mode."""

import pytest

from backend.services import portfolio_fetch


@pytest.mark.asyncio
async def test_fetch_recent_closed_trades_uses_agent_ledger_in_testnet(monkeypatch):
    async def fake_agent(*, symbol=None, limit=50, offset=0):
        return [{"trade_id": "agent_pos_1", "symbol": symbol or "BTCUSD", "data_source": "agent"}]

    monkeypatch.setattr(portfolio_fetch, "is_testnet_trading_mode", lambda: True)
    monkeypatch.setattr(portfolio_fetch, "is_recent_trades_suppressed", lambda: False)
    monkeypatch.setattr(
        "backend.services.agent_trade_ledger_service.get_agent_closed_trades",
        fake_agent,
    )

    rows = await portfolio_fetch.fetch_recent_closed_trades(db=None, limit=5)
    assert rows[0]["trade_id"] == "agent_pos_1"
