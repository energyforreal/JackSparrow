"""Tests for opened_at parsing and learning loop datetime handling."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.wallet_attribution import parse_utc_datetime
from agent.events.schemas import PositionClosedEvent


def test_parse_utc_datetime_iso_string():
    dt = parse_utc_datetime("2026-07-04T10:00:00+00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026


@pytest.mark.asyncio
async def test_position_closed_learning_parses_iso_entry_time():
    from agent.core.state_machine import AgentStateMachine

    sm = AgentStateMachine.__new__(AgentStateMachine)
    sm.current_state = None
    sm.context_manager = MagicMock()
    sm.context_manager.update_state = AsyncMock()
    sm.learning_system = MagicMock()
    sm.learning_system.record_trade_outcome = AsyncMock()
    sm.learning_system.get_updated_model_weights = AsyncMock(return_value={})
    sm.model_registry = MagicMock()
    sm.model_registry.models = {"m1": object()}
    sm.model_registry.model_weights = {"m1": 1.0}
    sm.model_registry.update_weights_from_performance = MagicMock()

    event = PositionClosedEvent(
        source="test",
        payload={
            "position_id": "pos_test",
            "symbol": "BTCUSD",
            "entry_price": 100.0,
            "exit_price": 101.0,
            "quantity": 1.0,
            "pnl": 0.5,
            "predicted_signal": "LONG",
            "entry_time": "2026-07-04T10:00:00+00:00",
            "timestamp": datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
            "model_predictions": [{"model": "m1", "signal": "LONG"}],
        },
    )

    with patch("agent.core.state_machine.settings") as mock_settings:
        mock_settings.agent_reflection_policy_feedback_enabled = False
        mock_settings.entry_quality_learning_enabled = False
        mock_settings.trade_outcomes_writes_enabled = False
        with patch(
            "agent.intelligence.market_fsm.market_fsm",
            MagicMock(on_position_closed=MagicMock()),
        ):
            with patch(
                "agent.intelligence.trade_archetype_memory.trade_archetype_memory",
                MagicMock(record=MagicMock()),
            ):
                await sm._handle_position_closed(event)

    sm.learning_system.record_trade_outcome.assert_awaited_once()
    outcome = sm.learning_system.record_trade_outcome.await_args[0][0]
    assert outcome.holding_period_hours == pytest.approx(2.0)
