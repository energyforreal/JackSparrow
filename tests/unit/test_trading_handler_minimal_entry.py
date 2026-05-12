"""Trading handler: AI_SIGNAL_MINIMAL_ENTRY_GATES relaxed entry path."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.config import settings
from agent.core.product_specs import ContractSpecs
from agent.events.handlers.trading_handler import TradingEventHandler
from agent.events.schemas import DecisionReadyEvent, EventType


class _FakePositionManager:
    def __init__(self, open_position: dict | None) -> None:
        self._open = open_position

    def get_position(self, symbol: str):
        return self._open


class _FakeExecutionModule:
    def __init__(self, open_position: dict | None) -> None:
        self.position_manager = _FakePositionManager(open_position)


@pytest.fixture
def _minimal_settings(monkeypatch):
    monkeypatch.setattr(settings, "ai_signal_minimal_entry_gates", True)
    monkeypatch.setattr(settings, "ai_signal_min_entry_confidence", 0.70)
    monkeypatch.setattr(settings, "use_notional_lot_sizing", False)
    monkeypatch.setattr(settings, "fixed_lot_size", 1)
    monkeypatch.setattr(settings, "min_lot_size", 1)
    monkeypatch.setattr(settings, "initial_balance", 500000.0)


@pytest.mark.asyncio
async def test_minimal_entry_publishes_above_floor(monkeypatch, _minimal_settings) -> None:
    """With minimal gates, synthesis BUY + raw confidence 0.71 reaches publish path."""
    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.event_bus.publish",
        capture_publish,
    )

    fake_state = MagicMock()
    fake_state.config = {"market_data": {"price": 50000.0}}
    fake_state.portfolio_value = 500000.0
    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.context_manager",
        MagicMock(get_state=lambda: fake_state),
    )

    async def fake_specs(symbol: str) -> ContractSpecs:
        return ContractSpecs(
            symbol="BTCUSD",
            contract_value_btc=0.001,
            tick_size=0.5,
            product_id=27,
            taker_commission_rate=0.0005,
        )

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.get_contract_specs",
        fake_specs,
    )

    risk = MagicMock()
    handler = TradingEventHandler(
        risk_manager=risk,
        delta_client=None,
        execution_module=_FakeExecutionModule(None),
    )
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        AsyncMock(side_effect=lambda c, mp: c),
    )

    now = datetime.now(timezone.utc)
    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.71,
            "position_size": 0.1,
            "timestamp": now,
            "reasoning_chain": {
                "market_context": {"features": {}},
                "model_predictions": [],
            },
        },
    )

    await handler.handle_decision_ready_for_trading(event)

    assert any(getattr(e, "event_type", None) == EventType.RISK_APPROVED for e in published)
    risk.validate_trade.assert_not_called()


@pytest.mark.asyncio
async def test_minimal_entry_rejects_below_floor(monkeypatch, _minimal_settings) -> None:
    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.event_bus.publish",
        capture_publish,
    )

    handler = TradingEventHandler(
        risk_manager=MagicMock(),
        delta_client=None,
        execution_module=_FakeExecutionModule(None),
    )
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        AsyncMock(side_effect=lambda c, mp: c),
    )

    now = datetime.now(timezone.utc)
    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.69,
            "position_size": 0.1,
            "timestamp": now,
            "reasoning_chain": {"market_context": {"features": {}}, "model_predictions": []},
        },
    )

    await handler.handle_decision_ready_for_trading(event)

    assert not any(getattr(e, "event_type", None) == EventType.RISK_APPROVED for e in published)


@pytest.mark.asyncio
async def test_minimal_entry_same_side_open_still_blocks(monkeypatch, _minimal_settings) -> None:

    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.event_bus.publish",
        capture_publish,
    )

    handler = TradingEventHandler(
        risk_manager=MagicMock(),
        delta_client=None,
        execution_module=_FakeExecutionModule({"status": "open", "side": "long"}),
    )
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        AsyncMock(side_effect=lambda c, mp: c),
    )

    now = datetime.now(timezone.utc)
    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.99,
            "position_size": 0.1,
            "timestamp": now,
            "reasoning_chain": {"market_context": {"features": {}}, "model_predictions": []},
        },
    )

    await handler.handle_decision_ready_for_trading(event)

    assert not any(getattr(e, "event_type", None) == EventType.RISK_APPROVED for e in published)


@pytest.mark.asyncio
async def test_minimal_entry_still_applies_debounce(monkeypatch, _minimal_settings) -> None:
    monkeypatch.setattr(settings, "trade_signal_debounce_seconds", 60)

    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.event_bus.publish",
        capture_publish,
    )

    fake_state = MagicMock()
    fake_state.config = {"market_data": {"price": 50000.0}}
    fake_state.portfolio_value = 500000.0
    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.context_manager",
        MagicMock(get_state=lambda: fake_state),
    )

    async def fake_specs(symbol: str) -> ContractSpecs:
        return ContractSpecs(
            symbol="BTCUSD",
            contract_value_btc=0.001,
            tick_size=0.5,
            product_id=27,
            taker_commission_rate=0.0005,
        )

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.get_contract_specs",
        fake_specs,
    )

    handler = TradingEventHandler(
        risk_manager=MagicMock(),
        delta_client=None,
        execution_module=_FakeExecutionModule(None),
    )
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        AsyncMock(side_effect=lambda c, mp: c),
    )

    now = datetime.now(timezone.utc)
    event_one = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.99,
            "position_size": 0.1,
            "timestamp": now,
            "reasoning_chain": {"market_context": {"features": {}}, "model_predictions": []},
        },
    )
    event_two = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.99,
            "position_size": 0.1,
            "timestamp": now,
            "reasoning_chain": {"market_context": {"features": {}}, "model_predictions": []},
        },
    )

    await handler.handle_decision_ready_for_trading(event_one)
    await handler.handle_decision_ready_for_trading(event_two)

    assert sum(1 for e in published if getattr(e, "event_type", None) == EventType.RISK_APPROVED) == 1
