"""V43 trade lifecycle hooks — breaks direct execution ↔ mcp_orchestrator imports."""

from __future__ import annotations

from typing import Optional


def record_v43_trade_executed(bar_index: int) -> None:
    """Stamp v43 frequency state after a fill."""
    from agent.core.mcp_orchestrator import mcp_orchestrator

    mcp_orchestrator.record_v43_trade_executed(bar_index)


def rollback_v43_signal_decision(bar_index: Optional[int] = None) -> None:
    """Roll back v43 debounce when execution fails after policy entry."""
    from agent.core.mcp_orchestrator import mcp_orchestrator

    mcp_orchestrator.rollback_v43_signal_decision(bar_index)


async def persist_v43_gate_state_after_trade(symbol: str) -> None:
    """Persist gate counters after fill."""
    from agent.core.mcp_orchestrator import mcp_orchestrator

    await mcp_orchestrator.persist_v43_gate_state_after_trade(symbol)
