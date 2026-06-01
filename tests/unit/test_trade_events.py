"""trade_events module exposes V43 hooks without importing execution."""

from __future__ import annotations

import agent.core.trade_events as trade_events


def test_trade_events_exports() -> None:
    assert callable(trade_events.record_v43_trade_executed)
    assert callable(trade_events.persist_v43_gate_state_after_trade)
