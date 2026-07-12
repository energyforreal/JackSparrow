"""Unit tests for hurst_v2 historical backtest tool."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.commands.hurst_v2_historical_backtest import (
    candles_to_dataframe,
    load_candles_json,
    render_markdown,
    run_backtest,
)


def _synth_candles(n: int = 800, seed: int = 42, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Geometric RW with optional drift
    rets = rng.normal(drift, 0.001, size=n)
    close = 100_000.0 * np.exp(np.cumsum(rets))
    high = close * (1.0 + rng.uniform(0, 0.0005, size=n))
    low = close * (1.0 - rng.uniform(0, 0.0005, size=n))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    ts = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1.0, 10.0, size=n),
        }
    )


def test_candles_to_dataframe_delta_shape() -> None:
    raw = [
        {"time": 1_700_000_000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3},
        {"timestamp": "2026-01-01T00:05:00Z", "o": 1.5, "h": 2, "l": 1, "c": 1.8, "v": 4},
    ]
    df = candles_to_dataframe(raw)
    assert len(df) == 2
    assert set(df.columns) >= {"timestamp", "open", "high", "low", "close", "volume"}


def test_load_candles_json_wrapped(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"result": {"candles": [{"time": 100, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]}}), encoding="utf-8")
    rows = load_candles_json(p)
    assert len(rows) == 1


def test_run_backtest_schema_and_flag_restore() -> None:
    from agent.core import config as cfg

    settings = cfg.settings
    orig = bool(getattr(settings, "agent_thesis_use_hurst_v2", False))
    settings.agent_thesis_use_hurst_v2 = False
    try:
        df = _synth_candles(700, drift=0.0002)
        report = run_backtest(df, warmup=400, horizon_bars=6, window=0, step=5)
        assert "legacy" in report and "hurst_v2" in report
        for arm in ("legacy", "hurst_v2"):
            r = report[arm]
            for key in ("n_fires", "n_long", "n_short", "ev_combined_pct", "fire_rate_pct"):
                assert key in r
        assert report["n_eval"] > 0
        assert report["hurst_distribution"]["hurst_60"]["n"] > 0
        assert report["hurst_distribution"]["hurst_60_v2"]["n"] > 0
        md = render_markdown(report)
        assert "Hurst v2 Historical Backtest" in md
        assert "legacy" in md
    finally:
        assert bool(getattr(settings, "agent_thesis_use_hurst_v2", False)) is False
        settings.agent_thesis_use_hurst_v2 = orig


def test_run_backtest_sliding_window() -> None:
    df = _synth_candles(650)
    report = run_backtest(df, warmup=400, horizon_bars=4, window=500, step=20)
    assert report["n_eval"] > 0
    assert report["window"] == 500
