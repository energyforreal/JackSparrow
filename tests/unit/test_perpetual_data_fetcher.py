"""Tests for perpetual data fetcher validation."""

from __future__ import annotations

import pytest

from agent.data.perpetual_data_fetcher import fetch_candles_paginated


def test_invalid_resolution_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid resolution"):
        fetch_candles_paginated("BTCUSD", "1d", 0, 1)
