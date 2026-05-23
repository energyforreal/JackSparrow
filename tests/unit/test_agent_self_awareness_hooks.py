"""Unit tests for position-close self-awareness hooks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from agent.core.agent_self_awareness_hooks import enrich_position_closed_payload
from agent.memory.vector_store import DecisionContext, VectorMemoryStore


@pytest.mark.asyncio
async def test_enrich_backfills_memory_and_reflection() -> None:
    store = VectorMemoryStore(max_memory_size=50, similarity_threshold=0.0)
    await store.initialize()
    chain_id = "hook-chain-1"
    ctx = DecisionContext(
        context_id=f"decision-{chain_id}-100",
        symbol="BTCUSD",
        timestamp=datetime.now(timezone.utc),
        features={"rsi_14": 48.0},
        market_context={},
        decision={"signal": "BUY", "reasoning_chain_id": chain_id},
    )
    await store.store_decision_context(ctx)

    payload = {
        "symbol": "BTCUSD",
        "position_id": "pos_hook",
        "reasoning_chain_id": chain_id,
        "predicted_signal": "BUY",
        "pnl": 25.0,
        "exit_reason": "take_profit",
        "confidence_at_entry": 0.75,
        "duration_seconds": 3600.0,
        "timestamp": datetime.now(timezone.utc),
    }

    with patch("agent.core.agent_self_awareness_hooks.settings") as mock_settings:
        mock_settings.agent_memory_outcome_backfill_enabled = True
        mock_settings.agent_reflection_advisory_enabled = True
        with patch(
            "agent.core.mcp_orchestrator.mcp_orchestrator",
            type("O", (), {"vector_store": store})(),
        ):
            await enrich_position_closed_payload(payload)

    assert "reflection_snapshot" in payload
    assert payload["reflection_snapshot"]["was_profitable"] is True
    loaded = await store.get_context_by_id(ctx.context_id)
    assert loaded is not None
    assert loaded.outcome is not None
    assert loaded.outcome["pnl"] == pytest.approx(25.0)
