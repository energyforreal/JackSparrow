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
async def test_calculate_position_size_applies_stricter_drawdown_adjustment(monkeypatch):
    manager = RiskManager()
    await manager.initialize(initial_balance=10_000.0)

    monkeypatch.setattr(manager.portfolio, "get_drawdown", lambda: 0.12)
    size = manager.calculate_position_size(
        signal_strength=1.0,
        volatility_regime="low",
        win_probability=0.55,
        risk_reward_ratio=2.0,
    )

    # Base size reaches max_position_size (0.10), then 0.4 adjustment => 0.04.
    assert size == pytest.approx(0.04, rel=1e-6)


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
