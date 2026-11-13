"""Causal candle, volume, and swing channels for one timeframe.

Every value at bar ``t`` uses bars at or before ``t``. Pattern-rule columns
are not computed here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.cpr_mtf.contract import (
    ATR_PERIOD,
    SEQUENCE_CHANNELS,
    VOLUME_BASELINE,
)
from research.cpr_mtf.swings import Swing, bars_since_scale, detect_swings, positive_atr

_EPS = 1e-9
_OHLCV = ("open", "high", "low", "close", "volume")


def causal_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average of true range, using the previous close.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: Averaging window. Earlier bars stay NaN.

    Returns:
        ATR aligned to ``close``. Bar ``t`` uses true ranges through ``t``.
    """
    n = len(close)
    prev = np.empty(n, dtype=np.float64)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    true_range = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev), np.abs(low - prev)),
    )
    atr = np.full(n, np.nan, dtype=np.float64)
    if n < period:
        return atr
    window = np.ones(period, dtype=np.float64) / float(period)
    valid = np.convolve(true_range, window, mode="valid")
    atr[period - 1 :] = valid
    return atr


def volume_baseline(volume: np.ndarray, window: int) -> np.ndarray:
    """Trailing mean of volume ending at the current bar.

    Args:
        volume: Volume per bar.
        window: Lookback length, including the current bar.

    Returns:
        Baseline aligned to ``volume``. Earlier bars stay NaN.
    """
    n = len(volume)
    baseline = np.full(n, np.nan, dtype=np.float64)
    if n < window:
        return baseline
    kernel = np.ones(window, dtype=np.float64) / float(window)
    valid = np.convolve(volume.astype(np.float64), kernel, mode="valid")
    baseline[window - 1 :] = valid
    return baseline


def add_sequence_features(
    frame: pd.DataFrame,
    timeframe: str,
) -> tuple[pd.DataFrame, list[Swing]]:
    """Append the 20 causal channels and the swing list for one timeframe.

    Args:
        frame: Completed OHLCV sorted by time.
        timeframe: ``15m``, ``1h``, or ``4h``.

    Returns:
        Feature frame aligned to a reset index, and swings in confirmation
        order. Candle channels stay NaN until ATR is finite. Volume ratio
        stays NaN until the trailing baseline is finite.

    Raises:
        ValueError: If a required column is missing or a channel was not built.
    """
    required = {"time", *_OHLCV}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"feature frame is missing columns: {sorted(missing)}")
    out = frame.loc[:, ["time", *_OHLCV]].copy()
    out["time"] = pd.to_datetime(out["time"], utc=True)
    out = out.sort_values("time", kind="mergesort").reset_index(drop=True)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    close = out["close"].to_numpy(dtype=np.float64)
    open_ = out["open"].to_numpy(dtype=np.float64)
    volume = out["volume"].to_numpy(dtype=np.float64)
    atr = causal_atr(high, low, close, ATR_PERIOD)
    baseline = volume_baseline(volume, VOLUME_BASELINE)
    out["atr"] = atr
    _write_candle_channels(out, open_, high, low, close, volume, atr, baseline)
    swings = detect_swings(out, timeframe, atr)
    for name, values in swing_channels(len(out), swings, close, atr).items():
        out[name] = values
    for name in SEQUENCE_CHANNELS:
        if name not in out.columns:
            raise ValueError(f"sequence channel was not computed: {name}")
    return out, swings


def swing_channels(
    n_bars: int,
    swings: list[Swing],
    close: np.ndarray,
    atr: np.ndarray,
) -> dict[str, np.ndarray]:
    """Fill swing event and geometry channels in one forward pass.

    Args:
        n_bars: Length of the series.
        swings: Swings in confirmation order.
        close: Close prices.
        atr: Causal ATR aligned to ``close``.

    Returns:
        The nine swing and geometry channels. A bar only sees swings whose
        confirmation index is at or before that bar.
    """
    high_flag = np.zeros(n_bars, dtype=np.float64)
    low_flag = np.zeros(n_bars, dtype=np.float64)
    high_prom = np.zeros(n_bars, dtype=np.float64)
    low_prom = np.zeros(n_bars, dtype=np.float64)
    bars_since = np.ones(n_bars, dtype=np.float64)
    high_slope = np.zeros(n_bars, dtype=np.float64)
    low_slope = np.zeros(n_bars, dtype=np.float64)
    swing_range = np.zeros(n_bars, dtype=np.float64)
    position = np.full(n_bars, 0.5, dtype=np.float64)
    by_bar: dict[int, list[Swing]] = {}
    for swing in swings:
        by_bar.setdefault(swing.confirmation_index, []).append(swing)
    scale = bars_since_scale()
    last_confirmation: int | None = None
    recent_high: Swing | None = None
    previous_high: Swing | None = None
    recent_low: Swing | None = None
    previous_low: Swing | None = None
    for index in range(n_bars):
        for swing in by_bar.get(index, []):
            if swing.swing_type == "high":
                high_flag[index] = 1.0
                high_prom[index] = swing.prominence_atr
                previous_high = recent_high
                recent_high = swing
            else:
                low_flag[index] = 1.0
                low_prom[index] = swing.prominence_atr
                previous_low = recent_low
                recent_low = swing
            last_confirmation = index
        if last_confirmation is not None:
            bars_since[index] = float(np.log1p(index - last_confirmation) / scale)
        atr_value = positive_atr(
            float(atr[index]) if index < len(atr) else np.nan,
            float(close[index]),
        )
        high_slope[index] = _pair_slope(previous_high, recent_high, atr_value)
        low_slope[index] = _pair_slope(previous_low, recent_low, atr_value)
        if recent_high is not None and recent_low is not None:
            upper = max(recent_high.pivot_price, recent_low.pivot_price)
            lower = min(recent_high.pivot_price, recent_low.pivot_price)
            span = upper - lower
            swing_range[index] = span / atr_value
            if span > _EPS:
                position[index] = (float(close[index]) - lower) / span
            else:
                position[index] = 0.5
    return {
        "swing_high_flag": high_flag,
        "swing_low_flag": low_flag,
        "swing_high_prominence_atr": high_prom,
        "swing_low_prominence_atr": low_prom,
        "bars_since_confirmed_swing": bars_since,
        "swing_high_slope": high_slope,
        "swing_low_slope": low_slope,
        "swing_range_atr": swing_range,
        "price_position_in_swing_range": position,
    }


def _write_candle_channels(
    frame: pd.DataFrame,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    atr: np.ndarray,
    baseline: np.ndarray,
) -> None:
    """Write the 11 candle and volume channels onto ``frame``."""
    n = len(close)
    prev = np.empty(n, dtype=np.float64)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    ready = np.isfinite(atr) & (atr > 0.0)
    body = np.abs(close - open_)
    upper = high - np.maximum(open_, close)
    lower = np.minimum(open_, close) - low
    span = high - low
    frame["open_atr"] = _divide(open_ - prev, atr, ready)
    frame["high_atr"] = _divide(high - prev, atr, ready)
    frame["low_atr"] = _divide(low - prev, atr, ready)
    frame["close_atr"] = _divide(close - prev, atr, ready)
    frame["body_size_atr"] = _divide(body, atr, ready)
    frame["upper_wick_atr"] = _divide(upper, atr, ready)
    frame["lower_wick_atr"] = _divide(lower, atr, ready)
    frame["range_atr"] = _divide(span, atr, ready)
    frame["body_to_range"] = _ratio(body, span, ready)
    frame["close_location"] = _ratio(close - low, span, ready)
    volume_ready = ready & np.isfinite(baseline) & (baseline > 0.0)
    frame["volume_ratio"] = _divide(volume, baseline, volume_ready)


def _divide(numer: np.ndarray, denom: np.ndarray, ready: np.ndarray) -> np.ndarray:
    """Divide where ``ready`` is true and leave the other rows NaN."""
    out = np.full(len(numer), np.nan, dtype=np.float64)
    out[ready] = numer[ready] / denom[ready]
    return out


def _ratio(numer: np.ndarray, denom: np.ndarray, ready: np.ndarray) -> np.ndarray:
    """Divide by a bar range, using 0 when the range is flat."""
    out = np.full(len(numer), np.nan, dtype=np.float64)
    safe = ready & (np.abs(denom) > _EPS)
    flat = ready & ~safe
    out[safe] = numer[safe] / denom[safe]
    out[flat] = 0.0
    return out


def _pair_slope(older: Swing | None, newer: Swing | None, atr_value: float) -> float:
    """ATR-per-bar slope between two confirmed pivots."""
    if older is None or newer is None:
        return 0.0
    span = newer.pivot_index - older.pivot_index
    if span <= 0 or atr_value <= 0.0:
        return 0.0
    return (newer.pivot_price - older.pivot_price) / atr_value / float(span)
