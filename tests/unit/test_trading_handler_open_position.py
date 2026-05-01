"""Trading handler: same-side entry blocked when a position is already open."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

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


@pytest.mark.asyncio
async def test_open_position_blocks_same_side_long_buys(monkeypatch) -> None:
    """Long + BUY should reject before risk/price path (open_position_blocks_entry)."""
    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.apply_v15_entry_gate",
        lambda sig, preds, feats: (sig, {}),
    )

    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.event_bus.publish",
        capture_publish,
    )

    risk = MagicMock()
    risk.validate_trade = AsyncMock(
        return_value={"approved": True, "reason": "ok", "adjusted_size": 0.1}
    )

    open_leg = {"status": "open", "side": "long"}
    handler = TradingEventHandler(
        risk_manager=risk,
        delta_client=None,
        execution_module=_FakeExecutionModule(open_leg),
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
            "reasoning_chain": {
                "market_context": {"features": {"volatility": 1.0, "adx_14": 20.0}},
                "model_predictions": [],
            },
        },
    )

    await handler.handle_decision_ready_for_trading(event)

    assert not any(getattr(e, "event_type", None) == EventType.RISK_APPROVED for e in published)


@pytest.mark.asyncio
async def test_signal_reversal_still_closes_when_opposite_signal(monkeypatch) -> None:
    """Long + SELL should call close_position (reversal path), not same-side block."""
    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.apply_v15_entry_gate",
        lambda sig, preds, feats: (sig, {}),
    )

    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(
        "agent.events.handlers.trading_handler.event_bus.publish",
        capture_publish,
    )

    close_mock = AsyncMock(return_value=MagicMock(success=True))

    open_leg = {"status": "open", "side": "long"}
    execution = _FakeExecutionModule(open_leg)
    execution.close_position = close_mock  # type: ignore[attr-defined]

    risk = MagicMock()
    handler = TradingEventHandler(
        risk_manager=risk,
        delta_client=None,
        execution_module=execution,
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
            "signal": "SELL",
            "confidence": 0.99,
            "position_size": 0.1,
            "timestamp": now,
            "reasoning_chain": {
                "market_context": {"features": {"volatility": 1.0, "adx_14": 20.0}},
                "model_predictions": [],
            },
        },
    )

    await handler.handle_decision_ready_for_trading(event)

    close_mock.assert_awaited_once_with("BTCUSD", exit_reason="signal_reversal")
