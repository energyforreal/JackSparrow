"""Tests for unified position_id between agent fill and backend persistence."""

from __future__ import annotations

import inspect
import uuid

from agent.events.schemas import OrderFillEvent
from backend.services.trade_persistence_service import TradePersistenceService


def test_order_fill_event_carries_position_id():
    position_id = str(uuid.uuid4())
    event = OrderFillEvent(
        source="execution_engine",
        payload={
            "order_id": "ord-1",
            "trade_id": "trade_ord-1_123",
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1.0,
            "fill_price": 90000.0,
            "position_id": position_id,
        },
    )
    assert event.payload["position_id"] == position_id


def test_create_trade_and_position_accepts_position_id_kwarg():
    params = inspect.signature(TradePersistenceService.create_trade_and_position).parameters
    assert "position_id" in params
    assert params["position_id"].default is None
