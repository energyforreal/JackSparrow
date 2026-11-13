"""Next-bar fills, stop-first handling, and overlap."""

from __future__ import annotations

import pandas as pd

from research.swinging.contract import SLIPPAGE_BPS
from research.swinging.outcomes import simulate_portfolio, simulate_setup
from tests.unit.swinging_fixtures import make_ohlcv

_SLIP = SLIPPAGE_BPS / 10_000.0


def _setup(index: int, direction: str = "long", timeframe: str = "5m", atr: float = 10.0) -> dict:
    frame = make_ohlcv(4)
    return {
        "setup_id": f"{timeframe}:{index}:{direction}",
        "signal_timestamp": pd.Timestamp(frame["time"].iloc[0]).isoformat(),
        "bar_index": index,
        "direction": direction,
        "timeframe": timeframe,
        "atr_14": atr,
    }


def test_entry_uses_the_next_open() -> None:
    bars = make_ohlcv(60, drift=0.0)
    bars.loc[0, "close"] = 50.0
    bars.loc[1, "open"] = 110.0
    outcome = simulate_setup(_setup(0, atr=50.0), bars)
    assert outcome is not None
    assert outcome["simulated"] is True
    assert outcome["entry_price"] == (110.0 * (1.0 + _SLIP))
    assert outcome["entry_price"] != 50.0


def test_stop_first_without_lower_timeframe() -> None:
    bars = make_ohlcv(6, drift=0.0)
    bars.loc[1, "open"] = 100.0
    bars.loc[1, "high"] = 160.0
    bars.loc[1, "low"] = 70.0
    outcome = simulate_setup(_setup(0, atr=10.0), bars)
    assert outcome is not None
    assert outcome["exit_reason"] == "stop_first"
    stop = 100.0 - 1.5 * 10.0
    assert outcome["exit_price"] == stop * (1.0 - _SLIP)


def test_lower_timeframe_takes_profit_before_the_stop() -> None:
    bars = make_ohlcv(4, freq="1h", drift=0.0)
    bars.loc[1, "open"] = 100.0
    bars.loc[1, "high"] = 160.0
    bars.loc[1, "low"] = 70.0
    entry = pd.Timestamp(bars["time"].iloc[1])
    lower = pd.DataFrame(
        {
            "time": [entry, entry + pd.Timedelta(minutes=5)],
            "open": [100.0, 116.0],
            "high": [130.0, 130.0],
            "low": [99.0, 99.0],
            "close": [115.0, 115.0],
            "volume": [1.0, 1.0],
        }
    )
    outcome = simulate_setup(_setup(0, timeframe="1h", atr=10.0), bars, lower_bars=lower)
    assert outcome is not None
    assert outcome["exit_reason"] == "take_profit"


def test_overlap_does_not_open_a_second_position() -> None:
    bars = make_ohlcv(30, drift=0.0)
    bars.loc[10, "high"] = 130.0
    first = _setup(2, atr=10.0)
    second = _setup(5, atr=10.0)
    second["setup_id"] = "second"
    first["signal_timestamp"] = pd.Timestamp(bars["time"].iloc[2]).isoformat()
    second["signal_timestamp"] = pd.Timestamp(bars["time"].iloc[5]).isoformat()
    result = simulate_portfolio(pd.DataFrame([first, second]), bars)
    reasons = result["exit_reason"].tolist()
    assert "overlap_rejected" in reasons
    assert "take_profit" in reasons
    rejected = result.loc[result["exit_reason"] == "overlap_rejected", "outcome_label"]
    assert rejected.isna().all()
