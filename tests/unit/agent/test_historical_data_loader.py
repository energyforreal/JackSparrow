"""Tests for Delta historical loader pagination and dedup."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.data import historical_data_loader as hdl


def test_cap_page_size_respects_delta_limit() -> None:
    assert hdl._cap_page_size(2000) == hdl.DELTA_MAX_PAGE_SIZE
    assert hdl._cap_page_size(100) == 100


def test_dedup_candles_by_time_last_write_wins() -> None:
    candles = [
        {"time": 100, "open": 1.0, "close": 1.1},
        {"time": 200, "open": 2.0, "close": 2.1},
        {"time": 200, "open": 3.0, "close": 3.1},
    ]
    out = hdl._dedup_candles_by_time(candles)
    assert len(out) == 2
    assert out[1]["open"] == 3.0


def test_resolution_1m_allowed() -> None:
    hdl._validate_resolution("1m")
    assert hdl.RESOLUTION_SECONDS["1m"] == 60
