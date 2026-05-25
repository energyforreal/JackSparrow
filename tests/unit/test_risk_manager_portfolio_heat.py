"""Unit tests for assess_risk portfolio heat alignment with config."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.risk.risk_manager import RiskManager


@pytest.mark.asyncio
async def test_assess_risk_uses_configured_max_portfolio_heat():
    manager = RiskManager()
    manager._initialized = True
    manager.portfolio = MagicMock()
    manager.portfolio.total_value = 100_000.0
    manager.risk_limits = {"max_portfolio_heat": 0.30, "max_position_size": 0.10}

    manager.assess_portfolio_risk = AsyncMock(
        return_value=SimpleNamespace(portfolio_heat=0.20, max_drawdown=0.05)
    )

    assessment = await manager.assess_risk(
        symbol="BTCUSD",
        side="long",
        proposed_size=0.05,
        entry_price=50_000.0,
    )

    assert assessment["can_trade"] is True
    assert assessment["risk_level"] == "medium"

    manager.assess_portfolio_risk = AsyncMock(
        return_value=SimpleNamespace(portfolio_heat=0.35, max_drawdown=0.05)
    )
    blocked = await manager.assess_risk(
        symbol="BTCUSD",
        side="long",
        proposed_size=0.05,
        entry_price=50_000.0,
    )

    assert blocked["can_trade"] is False
    assert blocked["risk_level"] == "high"
