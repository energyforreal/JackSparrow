"""Causal candle geometry for the recognition tensor.

Every value at bar ``t`` uses bars at or before ``t``. Pattern-rule columns
are not computed here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.recognition_15m.contract import (
    ATR_PERIOD,
    ENGINEERED_CHANNELS,
    LEVEL_LOOKBACK,
    LEVEL_NEAR_ATR,
    LEVEL_TOUCH_ATR,
    VOLUME_BASELINE,
    ZZ_TAU,
)

_EPS = 1e-9


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


def add_engineered_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Append scale-normalized geometry columns.

    Args:
        frame: Completed 15-minute OHLCV sorted by time.

    Returns:
        Copy with ``ENGINEERED_CHANNELS`` plus ``atr`` and ``volume_baseline``.
        ``atr`` and ``volume_baseline`` are scales, not model channels.

    Raises:
        ValueError: If a price column is missing.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Feature frame is missing columns: {sorted(missing)}")

    out = frame.copy()
    open_ = out["open"].to_numpy(dtype=np.float64)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    close = out["close"].to_numpy(dtype=np.float64)
    volume = out["volume"].to_numpy(dtype=np.float64)
    atr = causal_atr(high, low, close, ATR_PERIOD)
    baseline = volume_baseline(volume, VOLUME_BASELINE)
    span = high - low
    safe_span = span > 0.0
    body = np.abs(close - open_)
    upper = high - np.maximum(open_, close)
    lower = np.minimum(open_, close) - low
    atr_ready = np.isfinite(atr)
    safe_atr = np.where(atr_ready, np.maximum(atr, _EPS), np.nan)
    base_ready = np.isfinite(baseline)
    safe_base = np.where(base_ready, np.maximum(baseline, _EPS), np.nan)
    zeros = np.zeros(len(close), dtype=np.float64)
    midpoint = np.full(len(close), 0.5, dtype=np.float64)

    out["atr"] = atr
    out["volume_baseline"] = baseline
    out["body_size_atr"] = body / safe_atr
    out["upper_wick_atr"] = upper / safe_atr
    out["lower_wick_atr"] = lower / safe_atr
    out["range_atr"] = span / safe_atr
    out["body_to_range"] = np.divide(body, span, out=zeros.copy(), where=safe_span)
    out["upper_wick_to_range"] = np.divide(upper, span, out=zeros.copy(), where=safe_span)
    out["lower_wick_to_range"] = np.divide(lower, span, out=zeros.copy(), where=safe_span)
    out["close_location"] = np.divide(close - low, span, out=midpoint, where=safe_span)
    out["body_sign"] = np.sign(close - open_)
    delta = np.empty(len(close), dtype=np.float64)
    delta[0] = np.nan
    delta[1:] = close[1:] - close[:-1]
    out["close_change_atr"] = delta / safe_atr
    out["volume_ratio"] = volume / safe_base
    levels = causal_level_channels(high, low, close, atr)
    for name, values in levels.items():
        out[name] = values
    for name in ENGINEERED_CHANNELS:
        if name not in out.columns:
            raise ValueError(f"Engineered channel was not computed: {name}")
    return out


def causal_level_channels(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
) -> dict[str, np.ndarray]:
    """Support and resistance from swings confirmed by a 1.5 ATR reversal.

    A swing high or low is known at the bar where price has reversed by
    ``ZZ_TAU`` ATR. Bars after that confirmation are not read. The active
    level is the nearest confirmed extreme inside ``LEVEL_LOOKBACK`` bars.
    When that window has no extreme on one side, the last confirmed extreme
    on that side remains the level. Rows stay NaN until both sides exist.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        atr: Causal ATR aligned to ``close``.

    Returns:
        The seven ``level_*`` engineered channels.
    """
    n = len(close)
    support_dist = np.full(n, np.nan, dtype=np.float64)
    resistance_dist = np.full(n, np.nan, dtype=np.float64)
    at_support = np.full(n, np.nan, dtype=np.float64)
    at_resistance = np.full(n, np.nan, dtype=np.float64)
    support_touches = np.full(n, np.nan, dtype=np.float64)
    resistance_touches = np.full(n, np.nan, dtype=np.float64)
    range_position = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return _level_frame(
            support_dist,
            resistance_dist,
            at_support,
            at_resistance,
            support_touches,
            resistance_touches,
            range_position,
        )

    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    high_cursor = 0
    low_cursor = 0
    direction = 1
    extreme_price = float(high[0])
    for index in range(n):
        atr_value = _positive_atr(atr[index], float(close[index]))
        threshold = ZZ_TAU * atr_value
        if direction == 1:
            if float(high[index]) >= extreme_price:
                extreme_price = float(high[index])
            elif (extreme_price - float(low[index])) >= threshold:
                highs.append((index, extreme_price))
                direction = -1
                extreme_price = float(low[index])
        elif float(low[index]) <= extreme_price:
            extreme_price = float(low[index])
        elif (float(high[index]) - extreme_price) >= threshold:
            lows.append((index, extreme_price))
            direction = 1
            extreme_price = float(high[index])

        lookback_start = index - LEVEL_LOOKBACK + 1
        high_cursor = _advance_cursor(highs, high_cursor, lookback_start)
        low_cursor = _advance_cursor(lows, low_cursor, lookback_start)
        resistance = _select_level(highs, high_cursor, float(close[index]), below=False)
        support = _select_level(lows, low_cursor, float(close[index]), below=True)
        if support is None or resistance is None:
            continue
        support_dist[index] = (float(close[index]) - support) / atr_value
        resistance_dist[index] = (resistance - float(close[index])) / atr_value
        at_support[index] = (
            1.0 if abs(float(close[index]) - support) < LEVEL_NEAR_ATR * atr_value else 0.0
        )
        at_resistance[index] = (
            1.0
            if abs(float(close[index]) - resistance) < LEVEL_NEAR_ATR * atr_value
            else 0.0
        )
        support_touches[index] = _touch_count(
            lows, low_cursor, support, LEVEL_TOUCH_ATR * atr_value
        )
        resistance_touches[index] = _touch_count(
            highs, high_cursor, resistance, LEVEL_TOUCH_ATR * atr_value
        )
        span = resistance - support
        if span > 0.0:
            range_position[index] = (float(close[index]) - support) / span
        else:
            range_position[index] = 0.5
    return _level_frame(
        support_dist,
        resistance_dist,
        at_support,
        at_resistance,
        support_touches,
        resistance_touches,
        range_position,
    )


def _positive_atr(atr_value: float, price: float) -> float:
    """ATR divisor. A non-positive reading falls back to one percent of price."""
    if np.isfinite(atr_value) and float(atr_value) > 0.0:
        return float(atr_value)
    return max(abs(price) * 0.01, _EPS)


def _advance_cursor(points: list[tuple[int, float]], cursor: int, start: int) -> int:
    """Drop confirmed swings older than the lookback."""
    while cursor < len(points) and points[cursor][0] < start:
        cursor += 1
    return cursor


def _select_level(
    points: list[tuple[int, float]],
    cursor: int,
    price: float,
    *,
    below: bool,
) -> float | None:
    """Nearest extreme on one side of price, else the closest, else the last."""
    if not points:
        return None
    active = points[cursor:]
    pool = active if active else points[-1:]
    chosen: float | None = None
    for _, level in pool:
        if below and level <= price and (chosen is None or level > chosen):
            chosen = level
        if not below and level >= price and (chosen is None or level < chosen):
            chosen = level
    if chosen is not None:
        return chosen
    return min(pool, key=lambda item: abs(item[1] - price))[1]


def _touch_count(
    points: list[tuple[int, float]],
    cursor: int,
    level: float,
    band: float,
) -> float:
    """How many lookback extremes sit inside ``band`` of ``level``."""
    return float(sum(1 for _, price in points[cursor:] if abs(price - level) <= band))


def _level_frame(
    support_dist: np.ndarray,
    resistance_dist: np.ndarray,
    at_support: np.ndarray,
    at_resistance: np.ndarray,
    support_touches: np.ndarray,
    resistance_touches: np.ndarray,
    range_position: np.ndarray,
) -> dict[str, np.ndarray]:
    """Map level arrays onto the engineered channel names."""
    return {
        "level_support_dist_atr": support_dist,
        "level_resistance_dist_atr": resistance_dist,
        "level_at_support": at_support,
        "level_at_resistance": at_resistance,
        "level_support_touches": support_touches,
        "level_resistance_touches": resistance_touches,
        "level_range_position": range_position,
    }


def first_finite_bar(features: pd.DataFrame) -> int:
    """Return the first bar index whose engineered channels are all finite.

    Args:
        features: Frame returned by :func:`add_engineered_features`.

    Returns:
        Bar index. ``len(features)`` when no bar is finite.
    """
    matrix = features.loc[:, list(ENGINEERED_CHANNELS)].to_numpy(dtype=np.float64)
    finite = np.isfinite(matrix).all(axis=1)
    hits = np.flatnonzero(finite)
    if len(hits) == 0:
        return len(features)
    return int(hits[0])


def safe_scale(value: float) -> float:
    """Return a positive divisor for a price or volume scale."""
    if not np.isfinite(value) or value <= 0.0:
        return _EPS
    return float(value)
