"""Tests for exchange portfolio seed into RiskManager.Portfolio."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.core.portfolio_seed import seed_risk_manager_portfolio_from_exchange
from agent.risk.risk_manager import Portfolio


@pytest.mark.asyncio
async def test_seed_writes_cash_balance_not_total_value_property() -> None:
    portfolio = Portfolio(initial_balance=10_000.0)
    risk_manager = SimpleNamespace(portfolio=portfolio)
    execution = SimpleNamespace(
        get_exchange_portfolio_snapshot=AsyncMock(
            return_value={
                "wallet_balances": {
                    "meta": {"net_equity": 12345.0},
                    "result": [],
                }
            }
        )
    )

    seeded = await seed_risk_manager_portfolio_from_exchange(
        execution, risk_manager, "BTCUSD"
    )

    assert seeded == 12345.0
    assert portfolio.cash_balance == 12345.0
    assert portfolio.total_value == 12345.0
    assert portfolio.current_portfolio_value == 12345.0
    assert portfolio.peak_portfolio_value == 12345.0


@pytest.mark.asyncio
async def test_seed_resets_peak_when_wallet_below_initial_balance() -> None:
    """Avoid fake drawdown from INITIAL_BALANCE peak after exchange seed."""
    portfolio = Portfolio(initial_balance=20_000.0)
    assert portfolio.peak_portfolio_value == 20_000.0
    risk_manager = SimpleNamespace(portfolio=portfolio)
    execution = SimpleNamespace(
        get_exchange_portfolio_snapshot=AsyncMock(
            return_value={
                "wallet_balances": {
                    "meta": {"net_equity": 89.8},
                    "result": [],
                }
            }
        )
    )

    seeded = await seed_risk_manager_portfolio_from_exchange(
        execution, risk_manager, "BTCUSD"
    )

    assert seeded == 89.8
    assert portfolio.peak_portfolio_value == 89.8
    assert portfolio.get_drawdown() == 0.0
