"""Unit tests for agent.core.dynamic_sl_tp."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agent.core.dynamic_sl_tp import (
    compute_sl_tp_levels,
    should_update_bracket,
    to_delta_bracket_payload,
)


def _settings(**kwargs):
    base = dict(
        stop_loss_percentage=0.01,
        take_profit_percentage=0.02,
        use_atr_scaled_sl_tp=False,
        atr_sl_distance_mult=1.0,
        atr_tp_distance_mult=1.5,
        use_atr_trailing_stop=False,
        atr_trailing_mult=1.0,
        dynamic_sl_tp_min_adjust_interval_seconds=60,
        dynamic_sl_tp_min_price_change_pct=0.002,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_compute_sl_tp_levels_fixed_buy():
    levels = compute_sl_tp_levels(100_000.0, "BUY", None, None, _settings())
    assert levels.stop_loss == 99_000.0
    assert levels.take_profit == 102_000.0


def test_to_delta_bracket_payload_market_stops():
    from agent.core.dynamic_sl_tp import SlTpLevels

    body = to_delta_bracket_payload(
        SlTpLevels(99_000.0, 102_000.0),
        trigger_method="mark_price",
    )
    assert body["bracket_stop_trigger_method"] == "mark_price"
    assert body["stop_loss_order"]["stop_price"] == "99000.0"
    assert body["take_profit_order"]["stop_price"] == "102000.0"


def test_should_update_bracket_respects_interval():
    from agent.core.dynamic_sl_tp import SlTpLevels

    recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    pos = {
        "stop_loss": 99_000.0,
        "take_profit": 102_000.0,
        "bracket_sl_tp_updated_at": recent,
    }
    levels = SlTpLevels(98_000.0, 103_000.0)
    assert should_update_bracket(pos, levels, _settings()) is False
