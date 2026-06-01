"""Tests for Order state machine transitions."""

from agent.core.execution import Order


def test_order_fill_transitions():
    order = Order("o1", "BTCUSD", "buy", "market", 1.0)
    assert order.status == "pending"
    order.update_fill(1.0, 78000.0)
    assert order.status == "filled"


def test_order_cancel_transition():
    order = Order("o2", "BTCUSD", "buy", "market", 1.0)
    order.cancel()
    assert order.status == "cancelled"
