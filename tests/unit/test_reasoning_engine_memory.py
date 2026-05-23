"""Unit tests for reasoning engine historical memory (step 2)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest
from agent.memory.vector_store import DecisionContext, VectorMemoryStore


@pytest.mark.asyncio
async def test_step2_summarizes_similar_outcomes() -> None:
    store = VectorMemoryStore(max_memory_size=50, similarity_threshold=0.0)
    await store.initialize()

    ts = datetime.now(timezone.utc)
    ctx = DecisionContext(
        context_id=f"decision-memtest-{ts.timestamp():.0f}",
        symbol="BTCUSD",
        timestamp=ts,
        features={"rsi_14": 55.0},
        market_context={"market_regime": "neutral"},
        decision={"signal": "BUY", "reasoning_chain_id": "memtest"},
        outcome={"pnl": 15.0, "was_profitable": True, "exit_reason": "take_profit"},
    )
    ctx.compute_embedding()
    await store.store_decision_context(ctx)

    engine = MCPReasoningEngine(
        feature_server=MagicMock(),
        model_registry=MagicMock(),
        vector_store=store,
    )
    request = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context={"features": {"rsi_14": 55.0}},
        use_memory=True,
    )
    step = await engine._step2_historical_context(request, "query-chain")

    joined = " ".join(step.evidence or [])
    assert "similar historical contexts" in joined.lower() or "Similar setups" in joined
    assert step.similarity_score is not None or "unavailable" in joined.lower()


@pytest.mark.asyncio
async def test_step2_skips_when_memory_disabled() -> None:
    engine = MCPReasoningEngine(
        feature_server=MagicMock(),
        model_registry=MagicMock(),
        vector_store=None,
    )
    request = MCPReasoningRequest(
        symbol="BTCUSD",
        market_context={"features": {}},
        use_memory=False,
    )
    step = await engine._step2_historical_context(request, "q2")
    assert any("not configured" in e for e in (step.evidence or []))
