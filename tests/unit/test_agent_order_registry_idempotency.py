"""Decision event idempotency guard for agent entries."""

from agent.core.agent_order_registry import (
    is_decision_already_executed,
    record_decision_execution,
)


def test_decision_idempotency_blocks_duplicate() -> None:
    eid = "dec-test-001"
    assert is_decision_already_executed(eid) is False
    record_decision_execution(eid)
    assert is_decision_already_executed(eid) is True
