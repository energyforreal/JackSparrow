"""State machine transitions that affect signal freshness / THINKING recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.state_machine import AgentState, AgentStateMachine
from agent.events.schemas import DecisionReadyEvent, ModelPredictionCompleteEvent


@pytest.fixture
def state_machine() -> AgentStateMachine:
    ctx = MagicMock()
    ctx.update_state = AsyncMock()
    ctx.add_state_transition = MagicMock()
    sm = AgentStateMachine(context_manager=ctx)
    sm.current_state = AgentState.THINKING
    return sm


@pytest.mark.asyncio
async def test_decision_ready_from_thinking_hold_returns_to_observing(
    state_machine: AgentStateMachine,
) -> None:
    event = DecisionReadyEvent(
        source="test",
        payload={"signal": "HOLD", "confidence": 0.3},
    )
    state_machine._transition_to = AsyncMock()  # type: ignore[method-assign]

    await state_machine._handle_decision_ready(event)

    state_machine._transition_to.assert_awaited_once_with(
        AgentState.OBSERVING,
        "HOLD decision - returning to observation mode",
    )


@pytest.mark.asyncio
async def test_decision_ready_from_thinking_buy_goes_to_deliberating(
    state_machine: AgentStateMachine,
) -> None:
    event = DecisionReadyEvent(
        source="test",
        payload={"signal": "BUY", "confidence": 0.8},
    )
    state_machine._transition_to = AsyncMock()  # type: ignore[method-assign]

    await state_machine._handle_decision_ready(event)

    state_machine._transition_to.assert_awaited_once_with(
        AgentState.DELIBERATING,
        "Trade signal - awaiting risk approval",
    )


@pytest.mark.asyncio
async def test_prediction_error_from_thinking_returns_to_observing(
    state_machine: AgentStateMachine,
) -> None:
    event = ModelPredictionCompleteEvent(
        source="test",
        payload={
            "error": "timeout",
            "symbol": "BTCUSD",
            "request_context": {"trigger": "candle_closed"},
        },
    )
    state_machine._transition_to = AsyncMock()  # type: ignore[method-assign]

    await state_machine._handle_prediction_complete(event)

    state_machine._transition_to.assert_awaited_once_with(
        AgentState.OBSERVING,
        "Prediction failed - resuming observation",
    )


@pytest.mark.asyncio
async def test_prediction_error_from_fluctuation_ignored_in_thinking(
    state_machine: AgentStateMachine,
) -> None:
    event = ModelPredictionCompleteEvent(
        source="test",
        payload={
            "error": "No features available for prediction",
            "error_code": "NO_FEATURES",
            "symbol": "BTCUSD",
            "request_context": {},
        },
    )
    state_machine._transition_to = AsyncMock()  # type: ignore[method-assign]

    await state_machine._handle_prediction_complete(event)

    state_machine._transition_to.assert_not_called()
