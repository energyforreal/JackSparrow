"""Geometric labels and the causal zigzag market state.

Labels at bar ``t`` use bars at or before ``t``. Conventional names and
directional bias are written only onto the rule card.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from research.recognition_15m.contract import (
    DOJI_BODY_MAX,
    ENGULF_BODY_ATR_MIN,
    GEOMETRIC_CLASSES,
    HARAMI_PRIOR_ATR_MIN,
    MARKET_STATES,
    MARUBOZU_BODY_MIN,
    MARUBOZU_WICK_MAX,
    PRIOR_TREND_BARS,
    RANGE_ATR_MIN,
    RULE_CARD_COLUMNS,
    SOLDIER_BODY_MIN,
    SOLDIER_WICK_MAX,
    STAR_LARGE_BODY,
    STAR_SMALL_BODY,
    STRUCTURE_TAGS,
    TREND_FLAT_BAND,
    TWEEZER_ATR_TOL,
    TWEEZER_BODY_ATR_MIN,
    WICK_BODY_MIN,
    WICK_BODY_MULTIPLE,
    WICK_OPPOSITE_MAX,
    WINDOW_BARS,
    ZZ_EPS_ATR,
    ZZ_TAU,
)

_STATE_INDEX = {name: index for index, name in enumerate(MARKET_STATES)}
_TAG_INDEX = {name: index for index, name in enumerate(STRUCTURE_TAGS)}


def _parts(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return body, upper wick, lower wick, range, body ratio, and body sign."""
    span = high - low
    body = np.abs(close - open_)
    upper = high - np.maximum(open_, close)
    lower = np.minimum(open_, close) - low
    ratio = np.divide(body, span, out=np.zeros(len(span)), where=span > 0.0)
    sign = np.sign(close - open_)
    return body, upper, lower, span, ratio, sign


def geometry_matrix(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
) -> np.ndarray:
    """Multi-label geometric families aligned to each bar.

    Args:
        open_: Open prices.
        high: High prices.
        low: Low prices.
        close: Close prices.
        atr: Causal ATR. Non-finite rows stay negative.

    Returns:
        Float array of shape ``(n, len(GEOMETRIC_CLASSES))`` with 0/1 values.
    """
    n = len(close)
    body, upper, lower, span, body_ratio, sign = _parts(open_, high, low, close)
    upper_ratio = np.divide(upper, span, out=np.zeros(n), where=span > 0.0)
    lower_ratio = np.divide(lower, span, out=np.zeros(n), where=span > 0.0)
    atr_ok = np.isfinite(atr) & (atr > 0.0)
    wide = atr_ok & (span > RANGE_ATR_MIN * atr)

    long_lower = (
        wide
        & (lower >= WICK_BODY_MULTIPLE * body)
        & (upper_ratio < WICK_OPPOSITE_MAX)
        & (body_ratio > WICK_BODY_MIN)
    )
    long_upper = (
        wide
        & (upper >= WICK_BODY_MULTIPLE * body)
        & (lower_ratio < WICK_OPPOSITE_MAX)
        & (body_ratio > WICK_BODY_MIN)
    )
    doji = wide & (body_ratio < DOJI_BODY_MAX)
    marubozu = (
        wide
        & (body_ratio >= MARUBOZU_BODY_MIN)
        & (upper_ratio < MARUBOZU_WICK_MAX)
        & (lower_ratio < MARUBOZU_WICK_MAX)
    )

    labels = np.zeros((n, len(GEOMETRIC_CLASSES)), dtype=np.float32)
    labels[:, 0] = long_lower
    labels[:, 1] = long_upper
    labels[:, 2] = doji
    labels[:, 3] = marubozu
    if n >= 2:
        labels[1:, 4] = _engulfing(body, sign, atr, open_, close)
        labels[1:, 5] = _harami(body, sign, atr, open_, close)
        labels[1:, 6] = _piercing(sign, open_, close)
        labels[1:, 7] = _tweezer(high, low, body, sign, atr)
    if n >= 3:
        labels[2:, 8] = _star(body_ratio, sign, open_, close)
        labels[2:, 9] = _soldiers(body_ratio, upper_ratio, lower_ratio, sign, close)
    return labels


def _engulfing(
    body: np.ndarray,
    sign: np.ndarray,
    atr: np.ndarray,
    open_: np.ndarray,
    close: np.ndarray,
) -> np.ndarray:
    """Engulfing bits for bars 1..n-1."""
    prior_lo = np.minimum(open_[:-1], close[:-1])
    prior_hi = np.maximum(open_[:-1], close[:-1])
    cur_lo = np.minimum(open_[1:], close[1:])
    cur_hi = np.maximum(open_[1:], close[1:])
    large = (body[1:] > ENGULF_BODY_ATR_MIN * atr[1:]) & (
        body[:-1] > ENGULF_BODY_ATR_MIN * atr[1:]
    )
    opposite = sign[1:] * sign[:-1] < 0.0
    contains = (cur_lo <= prior_lo) & (cur_hi >= prior_hi)
    return (large & opposite & contains).astype(np.float32)


def _harami(
    body: np.ndarray,
    sign: np.ndarray,
    atr: np.ndarray,
    open_: np.ndarray,
    close: np.ndarray,
) -> np.ndarray:
    """Harami bits for bars 1..n-1."""
    prior_lo = np.minimum(open_[:-1], close[:-1])
    prior_hi = np.maximum(open_[:-1], close[:-1])
    cur_lo = np.minimum(open_[1:], close[1:])
    cur_hi = np.maximum(open_[1:], close[1:])
    prior_large = body[:-1] > HARAMI_PRIOR_ATR_MIN * atr[1:]
    inside = (cur_lo >= prior_lo) & (cur_hi <= prior_hi) & (body[1:] < body[:-1])
    opposite = sign[1:] * sign[:-1] < 0.0
    return (prior_large & inside & opposite & (body[1:] > 0.0)).astype(np.float32)


def _piercing(sign: np.ndarray, open_: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Piercing or dark-cloud bits for bars 1..n-1."""
    midpoint = (open_[:-1] + close[:-1]) * 0.5
    piercing = (
        (sign[:-1] < 0.0)
        & (sign[1:] > 0.0)
        & (open_[1:] <= close[:-1])
        & (close[1:] >= midpoint)
        & (close[1:] < open_[:-1])
    )
    dark = (
        (sign[:-1] > 0.0)
        & (sign[1:] < 0.0)
        & (open_[1:] >= close[:-1])
        & (close[1:] <= midpoint)
        & (close[1:] > open_[:-1])
    )
    return (piercing | dark).astype(np.float32)


def _tweezer(
    high: np.ndarray,
    low: np.ndarray,
    body: np.ndarray,
    sign: np.ndarray,
    atr: np.ndarray,
) -> np.ndarray:
    """Tweezer bits for bars 1..n-1."""
    tol = TWEEZER_ATR_TOL * atr[1:]
    bodies = (body[1:] > TWEEZER_BODY_ATR_MIN * atr[1:]) & (
        body[:-1] > TWEEZER_BODY_ATR_MIN * atr[1:]
    )
    opposite = sign[1:] * sign[:-1] < 0.0
    tops = np.abs(high[1:] - high[:-1]) <= tol
    bottoms = np.abs(low[1:] - low[:-1]) <= tol
    return (bodies & opposite & (tops | bottoms)).astype(np.float32)


def _star(
    body_ratio: np.ndarray,
    sign: np.ndarray,
    open_: np.ndarray,
    close: np.ndarray,
) -> np.ndarray:
    """Star bits for bars 2..n-1."""
    first_large = body_ratio[:-2] >= STAR_LARGE_BODY
    middle_small = body_ratio[1:-1] <= STAR_SMALL_BODY
    last_large = body_ratio[2:] >= STAR_LARGE_BODY
    opposite = sign[2:] * sign[:-2] < 0.0
    midpoint = (open_[:-2] + close[:-2]) * 0.5
    passed = ((sign[2:] > 0.0) & (close[2:] >= midpoint)) | (
        (sign[2:] < 0.0) & (close[2:] <= midpoint)
    )
    return (first_large & middle_small & last_large & opposite & passed).astype(
        np.float32
    )


def _soldiers(
    body_ratio: np.ndarray,
    upper_ratio: np.ndarray,
    lower_ratio: np.ndarray,
    sign: np.ndarray,
    close: np.ndarray,
) -> np.ndarray:
    """Three-soldier or three-crow bits for bars 2..n-1."""
    large = (
        (body_ratio[:-2] >= SOLDIER_BODY_MIN)
        & (body_ratio[1:-1] >= SOLDIER_BODY_MIN)
        & (body_ratio[2:] >= SOLDIER_BODY_MIN)
    )
    up = (
        (sign[:-2] > 0.0)
        & (sign[1:-1] > 0.0)
        & (sign[2:] > 0.0)
        & (close[1:-1] > close[:-2])
        & (close[2:] > close[1:-1])
        & (upper_ratio[:-2] < SOLDIER_WICK_MAX)
        & (upper_ratio[1:-1] < SOLDIER_WICK_MAX)
        & (upper_ratio[2:] < SOLDIER_WICK_MAX)
    )
    down = (
        (sign[:-2] < 0.0)
        & (sign[1:-1] < 0.0)
        & (sign[2:] < 0.0)
        & (close[1:-1] < close[:-2])
        & (close[2:] < close[1:-1])
        & (lower_ratio[:-2] < SOLDIER_WICK_MAX)
        & (lower_ratio[1:-1] < SOLDIER_WICK_MAX)
        & (lower_ratio[2:] < SOLDIER_WICK_MAX)
    )
    return (large & (up | down)).astype(np.float32)


def prior_context(close: np.ndarray) -> np.ndarray:
    """Context of bar ``t`` from closes ending at ``t - 1``.

    Args:
        close: Close prices.

    Returns:
        Object array of ``after_decline``, ``after_advance``, or ``after_flat``.
    """
    n = len(close)
    context = np.full(n, "after_flat", dtype=object)
    width = PRIOR_TREND_BARS
    if n <= width:
        return context
    kernel = np.ones(width, dtype=np.float64) / float(width)
    means = np.convolve(close.astype(np.float64), kernel, mode="valid")
    # means[k] ends at index k + width - 1. Bar t needs the mean ending at t - 1.
    for index in range(width, n):
        mean = float(means[index - width])
        previous = float(close[index - 1])
        if not np.isfinite(mean) or mean == 0.0:
            continue
        gap = (previous - mean) / mean
        if gap > TREND_FLAT_BAND:
            context[index] = "after_advance"
        elif gap < -TREND_FLAT_BAND:
            context[index] = "after_decline"
    return context


def build_rule_card(
    frame: pd.DataFrame,
    atr: np.ndarray,
    geometry: np.ndarray,
) -> pd.DataFrame:
    """Write conventional names beside geometric hits.

    Args:
        frame: OHLCV frame with a ``time`` column.
        atr: Causal ATR.
        geometry: Output of :func:`geometry_matrix`.

    Returns:
        One row per positive geometric class. These columns are not features.
    """
    open_ = frame["open"].to_numpy(dtype=np.float64)
    high = frame["high"].to_numpy(dtype=np.float64)
    low = frame["low"].to_numpy(dtype=np.float64)
    close = frame["close"].to_numpy(dtype=np.float64)
    context = prior_context(close)
    times = frame["time"].tolist()
    rows: list[dict[str, object]] = []
    for class_index, class_name in enumerate(GEOMETRIC_CLASSES):
        hits = np.flatnonzero(geometry[:, class_index] >= 0.5)
        for index in hits.tolist():
            name, bias, abstain = _interpret(
                class_name,
                int(index),
                open_,
                high,
                low,
                close,
                atr,
                str(context[index]),
            )
            rows.append(
                {
                    "bar_time": times[index],
                    "bar_index": int(index),
                    "geometric_class": class_name,
                    "conventional_name": name,
                    "directional_bias": bias,
                    "context": str(context[index]),
                    "abstain": bool(abstain),
                }
            )
    if not rows:
        return pd.DataFrame(columns=list(RULE_CARD_COLUMNS))
    card = pd.DataFrame(rows, columns=list(RULE_CARD_COLUMNS))
    return card


def _interpret(
    class_name: str,
    index: int,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    context: str,
) -> tuple[str, str, bool]:
    """Return conventional name, bias, and abstain for one geometric hit."""
    sign = float(np.sign(close[index] - open_[index]))
    if class_name == "long_lower_wick":
        if context == "after_decline":
            return "hammer", "bullish", False
        if context == "after_advance":
            return "hanging_man", "bearish", False
        return "long_lower_wick", "context_dependent", True
    if class_name == "long_upper_wick":
        if context == "after_advance":
            return "shooting_star", "bearish", False
        if context == "after_decline":
            return "inverted_hammer", "context_dependent", True
        return "long_upper_wick", "context_dependent", True
    if class_name == "doji":
        return "doji", "neutral", False
    if class_name == "marubozu":
        return _signed_name("marubozu", sign)
    if class_name == "engulfing":
        return _signed_name("engulfing", sign)
    if class_name == "harami":
        return _signed_name("harami", sign)
    if class_name == "piercing_dark_cloud":
        if sign > 0.0:
            return "piercing", "bullish", False
        if sign < 0.0:
            return "dark_cloud", "bearish", False
        return "piercing_dark_cloud", "context_dependent", True
    if class_name == "tweezer":
        return _tweezer_name(index, high, low, atr)
    if class_name == "star":
        return _signed_name("star", sign)
    if class_name == "soldiers_crows":
        if sign > 0.0:
            return "three_white_soldiers", "bullish", False
        if sign < 0.0:
            return "three_black_crows", "bearish", False
        return "soldiers_crows", "context_dependent", True
    return class_name, "context_dependent", True


def _signed_name(stem: str, sign: float) -> tuple[str, str, bool]:
    """Attach bullish or bearish from the completing candle's body sign."""
    if sign > 0.0:
        return f"bullish_{stem}", "bullish", False
    if sign < 0.0:
        return f"bearish_{stem}", "bearish", False
    return stem, "context_dependent", True


def _tweezer_name(
    index: int,
    high: np.ndarray,
    low: np.ndarray,
    atr: np.ndarray,
) -> tuple[str, str, bool]:
    """Name a tweezer from which side matched. Both sides abstain."""
    if index < 1 or not np.isfinite(atr[index]) or atr[index] <= 0.0:
        return "tweezer", "context_dependent", True
    tol = TWEEZER_ATR_TOL * float(atr[index])
    top = abs(float(high[index] - high[index - 1])) <= tol
    bottom = abs(float(low[index] - low[index - 1])) <= tol
    if top and bottom:
        return "tweezer", "context_dependent", True
    if top:
        return "tweezer_top", "bearish", False
    if bottom:
        return "tweezer_bottom", "bullish", False
    return "tweezer", "context_dependent", True


def confirmed_swing_events(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
) -> list[tuple[int, int, str]]:
    """Causal ATR zigzag events.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices, used only to keep ATR positive.
        atr: Causal ATR.

    Returns:
        Tuples of ``(confirmation_index, extreme_index, kind)`` with kind in
        ``HH``, ``HL``, ``LH``, ``LL``. A swing is recorded only when price
        has reversed by ``ZZ_TAU`` ATR. Later bars are not read.
    """
    n = len(close)
    if n == 0:
        return []
    direction = 1
    extreme_index = 0
    extreme_price = float(high[0])
    last_high = float("nan")
    last_low = float("nan")
    events: list[tuple[int, int, str]] = []
    for index in range(n):
        atr_value = float(atr[index]) if np.isfinite(atr[index]) else float("nan")
        if not np.isfinite(atr_value) or atr_value <= 0.0:
            atr_value = max(abs(float(close[index])) * 0.01, 1e-9)
        threshold = ZZ_TAU * atr_value
        band = ZZ_EPS_ATR * atr_value
        if direction == 1:
            if float(high[index]) >= extreme_price:
                extreme_price = float(high[index])
                extreme_index = index
            elif (extreme_price - float(low[index])) >= threshold:
                kind = _swing_kind(extreme_price, last_high, band, "HH", "LH")
                if kind is not None:
                    events.append((index, extreme_index, kind))
                last_high = extreme_price
                direction = -1
                extreme_price = float(low[index])
                extreme_index = index
        else:
            if float(low[index]) <= extreme_price:
                extreme_price = float(low[index])
                extreme_index = index
            elif (float(high[index]) - extreme_price) >= threshold:
                kind = _swing_kind(extreme_price, last_low, band, "HL", "LL")
                if kind is not None:
                    events.append((index, extreme_index, kind))
                last_low = extreme_price
                direction = 1
                extreme_price = float(high[index])
                extreme_index = index
    return events


def _swing_kind(
    price: float,
    previous: float,
    band: float,
    higher_name: str,
    lower_name: str,
) -> str | None:
    """Compare a confirmed extreme with the previous extreme of the same side."""
    if not np.isfinite(previous):
        return None
    if price > previous + band:
        return higher_name
    if price < previous - band:
        return lower_name
    return None


def market_labels(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    *,
    window: int = WINDOW_BARS,
) -> tuple[np.ndarray, np.ndarray]:
    """Window-level market state and structure tag at each bar.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        atr: Causal ATR.
        window: Bars visible to the label, including the current bar.

    Returns:
        Integer state ids and tag ids. A swing counts only when its extreme
        and its confirmation bar both sit inside the window ending at ``t``.
    """
    n = len(close)
    states = np.full(n, _STATE_INDEX["indeterminate"], dtype=np.int64)
    tags = np.full(n, _TAG_INDEX["none"], dtype=np.int64)
    events = confirmed_swing_events(high, low, close, atr)
    left = 0
    right = 0
    for end in range(n):
        start = end - window + 1
        while right < len(events) and events[right][0] <= end:
            right += 1
        while left < right and events[left][0] < start:
            left += 1
        visible = [
            kind
            for confirm, extreme, kind in events[left:right]
            if extreme >= start and confirm <= end
        ]
        state_name, tag_name = _state_from_events(visible)
        states[end] = _STATE_INDEX[state_name]
        tags[end] = _TAG_INDEX[tag_name]
    return states, tags


def _state_from_events(kinds: Iterable[str]) -> tuple[str, str]:
    """Map visible swing events to a market state and a structure tag."""
    sequence = list(kinds)
    if len(sequence) < 2:
        return "indeterminate", "none"
    bull = sum(kind in ("HH", "HL") for kind in sequence)
    bear = sum(kind in ("LH", "LL") for kind in sequence)
    last = sequence[-1]
    if last in ("LH", "LL") and bull >= 2 and bull > bear:
        return "transition", "hh_hl"
    if last in ("HH", "HL") and bear >= 2 and bear > bull:
        return "transition", "lh_ll"
    if bull >= 2 and bull > bear:
        return "uptrend", "hh_hl"
    if bear >= 2 and bear > bull:
        return "downtrend", "lh_ll"
    return "range_bound", "mixed"
