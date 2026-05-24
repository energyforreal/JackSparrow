"""Unit tests for agent.core.position_restore."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent.core.position_restore import restore_open_positions_from_db


@pytest.mark.asyncio
async def test_restore_passes_opened_at_as_entry_time(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "position_id": "pos_abc123456789",
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1.0,
            "entry_price": 80_000.0,
            "stop_loss": 79_000.0,
            "take_profit": 82_000.0,
            "opened_at": opened,
        }
    ]

    monkeypatch.setattr(
        "agent.core.position_restore._fetch_open_positions_sync",
        lambda _url: rows,
    )

    captured: dict = {}

    def _open_position(**kwargs):
        captured.update(kwargs)
        return {"symbol": kwargs["symbol"], "status": "open"}

    pm = MagicMock()
    pm.get_position.return_value = None
    pm.open_position.side_effect = _open_position
    execution_module = MagicMock()
    execution_module.position_manager = pm

    count = await restore_open_positions_from_db(execution_module, "postgresql://test")

    assert count == 1
    assert captured["position_extras"]["entry_time"] == opened
    assert captured["entry_price"] == 80_000.0
    assert captured["stop_loss"] == 79_000.0
