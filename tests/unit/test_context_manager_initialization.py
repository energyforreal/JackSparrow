"""Tests for context manager initialization and portfolio overlay wiring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.core.context_manager import ContextManager


@pytest.mark.asyncio
async def test_context_manager_initialize_enables_update_state(tmp_path: Path) -> None:
    manager = ContextManager(
        state_file=str(tmp_path / "agent_state.json"),
        backup_dir=str(tmp_path / "backups"),
    )
    await manager.initialize(load_existing=False, start_auto_save=False)

    updated = await manager.update_state(
        {
            "portfolio_value": 25000.0,
            "cash_balance": 24000.0,
        }
    )
    state = manager.get_state()

    assert updated is True
    assert state is not None
    assert state.portfolio_value == pytest.approx(25000.0)
    assert state.cash_balance == pytest.approx(24000.0)


@pytest.mark.asyncio
async def test_v43_portfolio_overlay_uses_initialized_state(tmp_path: Path, monkeypatch) -> None:
    import agent.core.context_manager as context_module

    manager = ContextManager(
        state_file=str(tmp_path / "overlay_state.json"),
        backup_dir=str(tmp_path / "overlay_backups"),
    )
    await manager.initialize(load_existing=False, start_auto_save=False)
    await manager.update_state(
        {
            "portfolio_value": 31250.0,
            "cash_balance": 30000.0,
            "positions": {"BTCUSD": {"size": 0.01}},
            "sharpe_ratio": 1.25,
            "max_drawdown": 0.08,
        }
    )

    monkeypatch.setattr(context_module, "context_manager", manager)
    from agent.core.mcp_orchestrator import _v43_reasoning_portfolio_risk_overlay

    overlay = _v43_reasoning_portfolio_risk_overlay("BTCUSD")

    assert overlay["portfolio_value"] == pytest.approx(31250.0)
    assert overlay["available_balance"] == pytest.approx(30000.0)
    assert overlay["sharpe_ratio_rolling"] == pytest.approx(1.25)
    assert overlay["max_drawdown_current"] == pytest.approx(0.08)
    assert overlay.get("has_open_position") is True
