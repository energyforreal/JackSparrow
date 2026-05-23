"""Unit tests for vector memory store outcome backfill and chain lookup."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.memory.vector_store import DecisionContext, VectorMemoryStore


@pytest.mark.asyncio
async def test_store_and_update_outcome() -> None:
    store = VectorMemoryStore(max_memory_size=100, similarity_threshold=0.0)
    await store.initialize()
    ctx = DecisionContext(
        context_id="decision-chain1-100",
        symbol="BTCUSD",
        timestamp=datetime.now(timezone.utc),
        features={"rsi_14": 55.0},
        market_context={"market_regime": "neutral"},
        decision={
            "signal": "BUY",
            "reasoning_chain_id": "chain1",
            "decision_event_id": "evt-1",
        },
        decision_event_id="evt-1",
    )
    await store.store_decision_context(ctx)
    ok = await store.update_context_outcome(
        "decision-chain1-100",
        {"pnl": 10.0, "was_profitable": True, "exit_reason": "take_profit"},
    )
    assert ok is True
    loaded = await store.get_context_by_id("decision-chain1-100")
    assert loaded is not None
    assert loaded.outcome["pnl"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_find_context_by_reasoning_chain_id() -> None:
    store = VectorMemoryStore(max_memory_size=100, similarity_threshold=0.0)
    await store.initialize()
    ts = datetime.now(timezone.utc)
    ctx = DecisionContext(
        context_id=f"decision-rc123-{ts.timestamp():.0f}",
        symbol="BTCUSD",
        timestamp=ts,
        features={"rsi_14": 50.0},
        market_context={},
        decision={"signal": "HOLD", "reasoning_chain_id": "rc123"},
    )
    await store.store_decision_context(ctx)
    found = await store.find_context_by_reasoning_chain_id("rc123")
    assert found is not None
    assert found.decision["reasoning_chain_id"] == "rc123"


@pytest.mark.asyncio
async def test_find_context_by_decision_event_id() -> None:
    store = VectorMemoryStore(max_memory_size=100, similarity_threshold=0.0)
    await store.initialize()
    ctx = DecisionContext(
        context_id="decision-x-1",
        symbol="BTCUSD",
        timestamp=datetime.now(timezone.utc),
        features={},
        market_context={},
        decision={"signal": "BUY"},
        decision_event_id="decision-evt-abc",
    )
    await store.store_decision_context(ctx)
    found = await store.find_context_by_decision_event_id("decision-evt-abc")
    assert found is not None
    assert found.context_id == "decision-x-1"
