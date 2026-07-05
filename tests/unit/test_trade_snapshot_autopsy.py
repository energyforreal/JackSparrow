"""Tests for trade autopsy fields in merge_close_fields."""

from __future__ import annotations

import pytest

from agent.persistence.trade_snapshot import merge_close_fields


def test_merge_close_fields_trade_autopsy_and_opened_at():
    entry = {
        "decision_context": {
            "ml_validation": {"expected_return": 0.012},
        },
        "execution_timing": {
            "position_opened_at": "2026-07-04T10:00:00+00:00",
        },
    }
    close = {
        "entry_price": 100.0,
        "exit_price": 101.0,
        "side": "long",
        "entry_time": "2026-07-04T10:00:00+00:00",
        "timestamp": "2026-07-04T12:00:00+00:00",
        "exit_reason": "stop_loss_hit",
        "pnl": -0.2,
        "gross_pnl_usd": 0.1,
        "excursions": {"mfe_pct": 0.015},
        "wallet_attribution": {"commission_usd": -0.31},
    }
    merged = merge_close_fields(entry, close)
    assert merged.get("opened_at") == "2026-07-04T10:00:00+00:00"
    autopsy = merged.get("trade_autopsy") or {}
    assert autopsy.get("expected_move_pct") == 0.012
    assert autopsy.get("actual_move_pct") == pytest.approx(0.01)
    assert autopsy.get("missed_move_pct") == pytest.approx(0.005)
    assert autopsy.get("commission_usd") == -0.31
