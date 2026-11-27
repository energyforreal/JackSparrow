"""Algorithmic multi-timeframe score, thresholds, and walk-forward replay."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.structure import add_market_structure_features
from research.swinging.algo_walkforward import tune_algo_weights, walk_forward_algo
from research.swinging.contract import ALGO_QUALIFIED_SCORE, ALGO_WEIGHTS
from research.swinging.mtf_score import decide_scores, resolve_weights, score_frames
from tests.unit.swinging_fixtures import make_ohlcv


def _rising(rows: int, freq: str, drift: float) -> pd.DataFrame:
    frame = make_ohlcv(rows, freq=freq, drift=drift, price=100.0)
    frame["volume"] = 10.0
    return frame


def _staircase(rows: int, freq: str) -> pd.DataFrame:
    """Rising swing legs so 1h structure can print HH/HL."""
    times = pd.date_range("2024-01-01", periods=rows, freq=freq, tz="UTC")
    close = np.zeros(rows, dtype=float)
    opened = np.zeros(rows, dtype=float)
    high = np.zeros(rows, dtype=float)
    low = np.zeros(rows, dtype=float)
    price = 100.0
    for index in range(rows):
        cycle = index % 20
        price += 8.0 if cycle < 12 else -2.0
        opened[index] = price - 1.0
        close[index] = price
        high[index] = max(opened[index], close[index]) + 1.0
        low[index] = min(opened[index], close[index]) - 1.0
    return pd.DataFrame(
        {
            "time": times,
            "open": opened,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(rows, 10.0),
        }
    )


def _bullish_confirmation(frame: pd.DataFrame) -> pd.DataFrame:
    """Force a bullish engulfing and a volume spike on the last 5m bar."""
    work = frame.copy()
    last = len(work) - 1
    previous_open = float(work.loc[last - 1, "open"])
    previous_close = float(work.loc[last - 1, "close"])
    if previous_close >= previous_open:
        work.loc[last - 1, "open"] = previous_close + 1.0
        work.loc[last - 1, "close"] = previous_close
    bear_open = float(work.loc[last - 1, "open"])
    bear_close = float(work.loc[last - 1, "close"])
    work.loc[last - 1, "high"] = max(bear_open, bear_close) + 0.2
    work.loc[last - 1, "low"] = min(bear_open, bear_close) - 0.2
    work.loc[last, "open"] = bear_close - 0.2
    work.loc[last, "close"] = bear_open + 0.8
    work.loc[last, "high"] = float(work.loc[last, "close"]) + 0.2
    work.loc[last, "low"] = float(work.loc[last, "open"]) - 0.1
    work.loc[last, "volume"] = 80.0
    return work


def _end_at(frame: pd.DataFrame, decision: pd.Timestamp, freq: str) -> pd.DataFrame:
    """Place the last bar so it closes exactly at ``decision``."""
    work = frame.copy()
    span = pd.Timedelta(freq) * (len(work) - 1)
    start = decision - pd.Timedelta(freq) - span
    work["time"] = pd.date_range(start, periods=len(work), freq=freq, tz="UTC")
    return work


def _frames() -> dict[str, pd.DataFrame]:
    """Higher timeframes contain many closed bars before the 5m decision."""
    four = _rising(70, "4h", 8.0)
    decision = pd.Timestamp(four["time"].iloc[60]) + pd.Timedelta(hours=4)
    one = _end_at(_staircase(160, "1h"), decision, "1h")
    fifteen = _end_at(_rising(80, "15min", 1.5), decision, "15min")
    five = _end_at(_rising(90, "5min", 0.8), decision, "5min")
    return {"5m": _bullish_confirmation(five), "15m": fifteen, "1h": one, "4h": four}


def test_design_weights_sum_to_100() -> None:
    assert sum(ALGO_WEIGHTS.values()) == 100.0
    assert resolve_weights(None) == {key: float(value) for key, value in ALGO_WEIGHTS.items()}


def test_threshold_holds_below_65_and_trades_at_65() -> None:
    held = decide_scores(long_score=ALGO_QUALIFIED_SCORE - 1.0, short_score=10.0)
    assert held["action"] == "abstain"
    assert held["signal"] == "HOLD"
    qualified = decide_scores(long_score=ALGO_QUALIFIED_SCORE, short_score=10.0)
    assert qualified["action"] == "long"
    assert qualified["signal"] == "BUY"
    strong = decide_scores(long_score=80.0, short_score=0.0)
    assert strong["signal"] == "STRONG_BUY"
    invalidated = decide_scores(
        long_score=90.0,
        short_score=0.0,
        long_invalidation="bearish_choch",
    )
    assert invalidated["action"] == "abstain"
    assert invalidated["invalidation"] == "bearish_choch"


def test_structure_exposes_bos_and_choch_without_contract_columns() -> None:
    from feature_store.transformer_btcusd.contract import NATIVE_STRUCTURE_COLS

    feat = add_market_structure_features(_rising(160, "1h", 4.0))
    for column in (
        "bos_up",
        "bos_down",
        "choch_up",
        "choch_down",
        "bars_since_bos",
        "bars_since_choch",
        "last_bos_side",
        "last_choch_side",
    ):
        assert column in feat.columns
        assert column not in NATIVE_STRUCTURE_COLS
        assert np.isfinite(feat[column].to_numpy()).all()


def test_uptrend_scores_a_long_and_flat_market_holds() -> None:
    scored = score_frames(_frames(), include_engine_a=False)
    assert scored["signal"] in ("BUY", "STRONG_BUY"), scored
    assert scored["action"] == "long"
    assert scored["score"] >= ALGO_QUALIFIED_SCORE
    assert scored["position_size"] == 0.0
    assert scored["confidence"] == pytest.approx(scored["score"] / 100.0)
    assert scored["long_components"]["trend_4h"] > 0.0
    assert scored["stop_price"] < scored["close"] < scored["take_profit_price"]

    flat = {
        "5m": make_ohlcv(90, freq="5min", drift=0.0),
        "15m": make_ohlcv(80, freq="15min", drift=0.0),
        "1h": make_ohlcv(80, freq="1h", drift=0.0),
        "4h": make_ohlcv(80, freq="4h", drift=0.0),
    }
    held = score_frames(flat, include_engine_a=False)
    assert held["signal"] == "HOLD", held
    assert held["score"] < ALGO_QUALIFIED_SCORE


def test_data_gate_rejects_stale_unclosed_and_invalid_candles() -> None:
    from research.swinging.quality import decision_data_issues

    frames = _frames()
    opened = pd.Timestamp(frames["5m"]["time"].iloc[-1])
    if opened.tzinfo is None:
        opened = opened.tz_localize("UTC")
    closed = opened + pd.Timedelta(minutes=5)
    assert decision_data_issues(frames, now=closed) == []
    stale = decision_data_issues(frames, now=closed + pd.Timedelta(days=3))
    assert any(item.startswith("stale_") for item in stale)
    inside_bar = decision_data_issues(frames, now=opened + pd.Timedelta(minutes=1))
    assert "five_minute_not_closed" not in inside_bar
    assert not any(item.startswith("stale_") for item in inside_bar)
    lone = {name: frame.copy() for name, frame in frames.items()}
    lone["5m"] = frames["5m"].iloc[-1:].reset_index(drop=True)
    unclosed = decision_data_issues(lone, now=opened + pd.Timedelta(minutes=1))
    assert "five_minute_not_closed" in unclosed
    broken = {name: frame.copy() for name, frame in frames.items()}
    broken["1h"].loc[broken["1h"].index[-1], "high"] = 1.0
    broken["1h"].loc[broken["1h"].index[-1], "low"] = 50.0
    assert "invalid_1h" in decision_data_issues(broken)
    held = score_frames(broken, include_engine_a=False)
    assert held["signal"] == "HOLD"
    assert held["position_size"] == 0.0


def test_live_clock_scores_the_previous_closed_bar() -> None:
    """A forming last 5m row must not zero the score or be traded."""
    frames = _frames()
    opened = pd.Timestamp(frames["5m"]["time"].iloc[-1])
    if opened.tzinfo is None:
        opened = opened.tz_localize("UTC")
    previous_close = float(frames["5m"]["close"].iloc[-2])
    scored = score_frames(
        frames,
        prepared=frames,
        now=opened + pd.Timedelta(minutes=1),
        include_engine_a=False,
    )
    assert scored.get("invalidation") != "five_minute_not_closed"
    assert scored.get("data_issues") is None
    assert scored["bar_index"] == len(frames["5m"]) - 2
    assert scored["close"] == pytest.approx(previous_close)


def test_walk_forward_reports_cost_adjusted_expectancy() -> None:
    report = walk_forward_algo(_frames(), n_splits=2, embargo=2)
    assert report["qualified_score"] == ALGO_QUALIFIED_SCORE
    assert "net_expectancy" in report["development"]
    assert "net_expectancy" in report["sealed_test"]
    assert report["weights"]["trend_4h"] == ALGO_WEIGHTS["trend_4h"]


def test_weight_search_does_not_fit_a_model() -> None:
    import pytest

    pytest.importorskip("optuna")
    source = inspect.getsource(tune_algo_weights)
    assert "xgboost" not in source
    assert "lightgbm" not in source
    tuned = tune_algo_weights(_frames(), n_trials=2)
    assert set(tuned["weights"]) == set(ALGO_WEIGHTS)
    assert sum(tuned["weights"].values()) == pytest.approx(100.0)
    assert tuned["high_quality_score"] >= tuned["qualified_score"]
