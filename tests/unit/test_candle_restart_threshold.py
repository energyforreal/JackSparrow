"""Unit tests for interval-aware candle restart threshold."""

from agent.core.intelligent_agent import effective_no_candle_restart_minutes


def test_effective_no_candle_restart_minutes_scales_with_5m_interval():
    assert effective_no_candle_restart_minutes("5m", 2) == 12
    assert effective_no_candle_restart_minutes("5m", 8) == 12


def test_effective_no_candle_restart_minutes_respects_higher_config():
    assert effective_no_candle_restart_minutes("5m", 15) == 15


def test_effective_no_candle_restart_minutes_for_1m_interval():
    assert effective_no_candle_restart_minutes("1m", 8) == 8
