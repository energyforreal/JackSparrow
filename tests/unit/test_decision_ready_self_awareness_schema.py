"""Contract tests for self-awareness fields on DecisionReadyEvent."""

from __future__ import annotations

from agent.events.schemas import AgentIntrospectionSnapshot, DecisionReadyEvent


def test_decision_ready_payload_accepts_introspection_fields() -> None:
    intro = AgentIntrospectionSnapshot(
        symbol="BTCUSD",
        policy_signal="HOLD",
        policy_confidence=0.5,
    )
    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "HOLD",
            "confidence": 0.5,
            "position_size": 0.0,
            "reasoning_chain": {"chain_id": "c1", "steps": []},
            "timestamp": "2026-05-22T12:00:00",
            "agent_introspection": intro.model_dump(),
            "memory_context_id": "decision-c1-100",
            "decision_event_id": "evt-test",
        },
    )
    assert event.payload["agent_introspection"]["symbol"] == "BTCUSD"
    assert event.payload["memory_context_id"] == "decision-c1-100"
