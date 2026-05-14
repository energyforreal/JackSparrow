"""Unit tests for RiskManager guardrails and sizing behavior."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RISK_MANAGER_PATH = ROOT / "agent" / "risk" / "risk_manager.py"
spec = importlib.util.spec_from_file_location("risk_manager_module", RISK_MANAGER_PATH)
assert spec and spec.loader
risk_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(risk_module)

Position = risk_module.Position
RiskManager = risk_module.RiskManager


@pytest.mark.asyncio
async def test_calculate_position_size_scales_with_confidence(monkeypatch):
    """Higher confidence yields larger capped position fraction than lower confidence."""
    manager = RiskManager()
    await manager.initialize(initial_balance=10_000.0)

    high = manager.calculate_position_size(
        mark_price=50_000.0,
        confidence=1.0,
        funding_rate=0.0,
        volatility=0.02,
    )
    low = manager.calculate_position_size(
        mark_price=50_000.0,
        confidence=0.5,
        funding_rate=0.0,
        volatility=0.02,
    )

    assert high >= low
    assert 0.01 <= high <= 0.1
    assert 0.01 <= low <= 0.1


@pytest.mark.asyncio
async def test_validate_trade_rejects_zero_entry_price_for_stop_loss_suggestion():
    manager = RiskManager()
    await manager.initialize(initial_balance=10_000.0)

    result = await manager.validate_trade(
        symbol="BTCUSD",
        side="long",
        proposed_size=0.05,
        entry_price=0.0,
        stop_loss=None,
    )

    assert result["approved"] is False
    assert "Invalid position size/entry price" in result["reason"]


@pytest.mark.asyncio
async def test_validate_trade_rejects_zero_entry_price_for_stop_loss_validation():
    manager = RiskManager()
    await manager.initialize(initial_balance=10_000.0)

    result = await manager.validate_trade(
        symbol="BTCUSD",
        side="long",
        proposed_size=0.05,
        entry_price=0.0,
        stop_loss=49_000.0,
    )

    assert result["approved"] is False
    assert "Invalid position size/entry price" in result["reason"]


@pytest.mark.asyncio
async def test_optimal_allocation_returns_empty_when_position_slots_full():
    manager = RiskManager()
    await manager.initialize(initial_balance=10_000.0)

    for idx in range(manager.risk_limits["max_open_positions"]):
        manager.portfolio.add_position(
            Position(
                symbol=f"SYM{idx}",
                side="long",
                size=1.0,
                entry_price=100.0,
                entry_time=datetime.now(timezone.utc),
            )
        )

    allocation = await manager.calculate_portfolio_optimal_allocation(
        available_symbols=["BTCUSD", "ETHUSD"],
        predictions={"BTCUSD": 0.8, "ETHUSD": 0.6},
    )

    assert allocation == {}
