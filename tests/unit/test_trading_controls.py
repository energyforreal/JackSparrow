"""Tests for kill switch and trading halt controls."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.core.trading_controls import (
    activate_kill_switch,
    clear_kill_switch,
    exchange_circuit_breaker_open,
    is_kill_switch_active,
    recover_from_emergency_stop,
    should_block_new_orders,
)


@pytest.fixture(autouse=True)
def reset_kill_switch():
    clear_kill_switch()
    yield
    clear_kill_switch()


def test_kill_switch_runtime_activation():
    assert not is_kill_switch_active()
    activate_kill_switch("test_halt", persist_context=False)
    assert is_kill_switch_active()
    blocked, reason = should_block_new_orders()
    assert blocked
    assert "test_halt" in reason


def test_recover_from_emergency_stop_clears_context():
    activate_kill_switch("halt", persist_context=True)
    recover_from_emergency_stop()
    assert not is_kill_switch_active()
    from agent.core.context_manager import context_manager

    assert context_manager.current_state.emergency_stop is False
    assert context_manager.current_state.trading_enabled is True
    assert context_manager.current_state.manual_reset is True


def test_circuit_breaker_open_blocks():
    from agent.data.delta_client import CircuitBreaker, CircuitBreakerState

    client = MagicMock()
    client.circuit_breaker = CircuitBreaker()
    client.circuit_breaker.state = CircuitBreakerState.OPEN
    assert exchange_circuit_breaker_open(client)
    blocked, reason = should_block_new_orders(client)
    assert blocked
    assert "circuit breaker" in reason.lower()
