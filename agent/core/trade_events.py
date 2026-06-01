"""V43 trade lifecycle hooks — breaks direct execution ↔ mcp_orchestrator imports."""

from __future__ import annotations


def record_v43_trade_executed(bar_index: int) -> None:
    """Stamp v43 frequency state after a fill."""
    from agent.core.mcp_orchestrator import mcp_orchestrator

    mcp_orchestrator.record_v43_trade_executed(bar_index)


async def persist_v43_gate_state_after_trade(symbol: str) -> None:
    """Persist gate counters after fill."""
    from agent.core.mcp_orchestrator import mcp_orchestrator

    await mcp_orchestrator.persist_v43_gate_state_after_trade(symbol)
