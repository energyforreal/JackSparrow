"""Tests for EventBus.unsubscribe."""

from __future__ import annotations

import pytest

from agent.events.event_bus import EventBus
from agent.events.schemas import EventType


@pytest.mark.asyncio
async def test_unsubscribe_removes_handler() -> None:
    bus = EventBus()

    async def handler(_event):
        pass

    bus.subscribe(EventType.DECISION_READY, handler)
    assert bus.unsubscribe(EventType.DECISION_READY, handler) is True
    assert bus.handlers.get(EventType.DECISION_READY, []) == []
