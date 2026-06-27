"""Tests for startup trading guards."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.core.startup_guard import (
    mark_trading_started,
    reset_trading_started_for_tests,
    startup_grace_blocks_entry,
)
from agent.events.handlers.trading_handler import _non_tradable_entry_reason


@pytest.fixture(autouse=True)
def _reset_startup_guard() -> None:
    reset_trading_started_for_tests()
    yield
    reset_trading_started_for_tests()


def test_non_tradable_warmup_trigger() -> None:
    reason = _non_tradable_entry_reason(
        {"signal": "BUY"},
        {"trigger": "model_health_warmup"},
    )
    assert reason == "warmup_trigger"


def test_non_tradable_dry_run() -> None:
    reason = _non_tradable_entry_reason(
        {"signal": "BUY"},
        {"dry_run": True},
    )
    assert reason == "dry_run_context"


def test_startup_grace_blocks_when_configured() -> None:
    mark_trading_started()
    with patch("agent.core.startup_guard.settings") as mock_settings:
        mock_settings.agent_startup_entry_grace_seconds = 60.0
        assert startup_grace_blocks_entry() is True
        reason = _non_tradable_entry_reason({"signal": "BUY"}, {})
        assert reason == "startup_entry_grace"


def test_live_candle_close_not_blocked() -> None:
    reason = _non_tradable_entry_reason(
        {"signal": "BUY", "tradable": True},
        {"trigger": "candle_closed"},
    )
    assert reason is None
