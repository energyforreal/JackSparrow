"""Tests for daily drawdown halt in RiskManager."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agent.risk.risk_manager import Portfolio, RiskManager


@pytest.mark.asyncio
async def test_daily_drawdown_halt_blocks_trading():
    rm = RiskManager()
    rm.portfolio = Portfolio(initial_balance=10000.0)
    rm.portfolio.peak_portfolio_value = 10000.0
    rm.portfolio.current_portfolio_value = 9400.0
    rm._initialized = True

    with patch("agent.core.config.settings") as mock_settings:
        mock_settings.agent_daily_drawdown_halt_pct = 4.0
        mock_settings.max_drawdown = 0.5
        mock_settings.max_position_size = 0.1
        mock_settings.max_portfolio_heat = 0.5
        mock_settings.max_leverage = 10
        mock_settings.max_open_positions = 5
        assessment = await rm.assess_portfolio_risk()

    assert assessment.can_trade is False

    with patch("agent.core.position_reconcile.is_reconcile_healthy", return_value=True):
        with patch("agent.core.trading_controls.should_block_new_orders", return_value=(False, "")):
            validation = await rm.validate_trade(
                symbol="BTCUSD",
                side="long",
                proposed_size=0.05,
                entry_price=78000.0,
            )

    assert validation["approved"] is False
