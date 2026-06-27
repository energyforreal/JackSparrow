"""Unit tests for agent.core.signal_vocabulary."""

from agent.core.signal_vocabulary import (
    is_entry_signal,
    is_long_signal,
    is_short_signal,
    normalize_signal,
    parse_entry_side,
    signal_from_side_and_confidence,
    signal_to_position_side,
    to_legacy_signal,
)


def test_normalize_legacy_aliases():
    assert normalize_signal("BUY") == "LONG"
    assert normalize_signal("STRONG_SELL") == "STRONG_SHORT"
    assert normalize_signal("LONG") == "LONG"


def test_signal_to_position_side():
    assert signal_to_position_side("STRONG_LONG") == "long"
    assert signal_to_position_side("SHORT") == "short"
    assert signal_to_position_side("HOLD") is None


def test_parse_entry_side():
    assert parse_entry_side("BUY") == "long"
    assert parse_entry_side("short") == "short"


def test_signal_from_side_and_confidence():
    assert signal_from_side_and_confidence("LONG", 0.9) == "STRONG_LONG"
    assert signal_from_side_and_confidence("SHORT", 0.5) == "SHORT"


def test_to_legacy_signal():
    assert to_legacy_signal("LONG") == "BUY"
    assert to_legacy_signal("STRONG_SHORT") == "STRONG_SELL"


def test_entry_signal_checks():
    assert is_entry_signal("LONG")
    assert is_long_signal("BUY")
    assert is_short_signal("STRONG_SHORT")
