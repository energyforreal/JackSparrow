"""Causal ATR swings with separate pivot and confirmation times.

A swing enters the record on the bar where price has reversed by 1.5 ATR.
Later bars are not read, and the first extreme on each side is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from research.cpr_mtf.contract import WINDOW_BARS, ZZ_TAU

_EPS = 1e-9


@dataclass(frozen=True)
class Swing:
    """One confirmed swing extreme.

    Attributes:
        swing_type: ``high`` or ``low``.
        pivot_index: Bar of the extreme.
        confirmation_index: Bar where the reversal became known.
        pivot_price: Extreme price.
        confirmation_price: Close at the confirmation bar.
        atr_at_pivot: Causal ATR at the pivot, with a price fallback.
        prominence_atr: Confirming reversal distance divided by ATR.
        timeframe: ``15m``, ``1h``, or ``4h``.
        pivot_time: Timestamp of the pivot bar.
        confirmation_time: Timestamp of the confirmation bar.
    """

    swing_type: str
    pivot_index: int
    confirmation_index: int
    pivot_price: float
    confirmation_price: float
    atr_at_pivot: float
    prominence_atr: float
    timeframe: str
    pivot_time: pd.Timestamp
    confirmation_time: pd.Timestamp


def positive_atr(atr_value: float, price: float) -> float:
    """ATR divisor. A non-positive reading falls back to one percent of price.

    Args:
        atr_value: Causal ATR reading.
        price: Price used for the fallback scale.

    Returns:
        A positive ATR value.
    """
    if np.isfinite(atr_value) and float(atr_value) > 0.0:
        return float(atr_value)
    return max(abs(float(price)) * 0.01, _EPS)


def detect_swings(
    frame: pd.DataFrame,
    timeframe: str,
    atr: np.ndarray,
) -> list[Swing]:
    """Record every extreme confirmed by a 1.5 ATR reversal.

    Args:
        frame: OHLCV sorted so that row position is the bar index.
        timeframe: Timeframe stored on each swing.
        atr: Causal ATR aligned to ``frame``.

    Returns:
        Swings in confirmation order. The pivot index is the extreme bar,
        which is always at or before the confirmation index.
    """
    high = frame["high"].to_numpy(dtype=np.float64)
    low = frame["low"].to_numpy(dtype=np.float64)
    close = frame["close"].to_numpy(dtype=np.float64)
    times = pd.to_datetime(frame["time"], utc=True)
    n = len(close)
    if n == 0:
        return []
    direction = 1
    extreme_index = 0
    extreme_price = float(high[0])
    swings: list[Swing] = []
    for index in range(n):
        atr_value = positive_atr(float(atr[index]), float(close[index]))
        threshold = ZZ_TAU * atr_value
        if direction == 1:
            if float(high[index]) >= extreme_price:
                extreme_price = float(high[index])
                extreme_index = index
            elif (extreme_price - float(low[index])) >= threshold:
                distance = extreme_price - float(low[index])
                swings.append(
                    _record(
                        "high",
                        extreme_index,
                        index,
                        extreme_price,
                        float(close[index]),
                        distance / atr_value,
                        high,
                        close,
                        atr,
                        times,
                        timeframe,
                    )
                )
                direction = -1
                extreme_price = float(low[index])
                extreme_index = index
        elif float(low[index]) <= extreme_price:
            extreme_price = float(low[index])
            extreme_index = index
        elif (float(high[index]) - extreme_price) >= threshold:
            distance = float(high[index]) - extreme_price
            swings.append(
                _record(
                    "low",
                    extreme_index,
                    index,
                    extreme_price,
                    float(close[index]),
                    distance / atr_value,
                    low,
                    close,
                    atr,
                    times,
                    timeframe,
                )
            )
            direction = 1
            extreme_price = float(high[index])
            extreme_index = index
    return swings


def visible_swings(swings: Sequence[Swing], asof_index: int) -> list[Swing]:
    """Return swings whose confirmation bar is at or before ``asof_index``.

    Args:
        swings: Swings in any order.
        asof_index: Last bar the caller is allowed to know.

    Returns:
        Confirmed swings, stable in input order.
    """
    return [swing for swing in swings if swing.confirmation_index <= asof_index]


def swings_on_chart(
    swings: Sequence[Swing],
    asof_index: int,
    window_start: int,
) -> list[Swing]:
    """Return confirmed swings whose pivot lies inside the drawn window.

    Args:
        swings: Full swing list.
        asof_index: Last visible bar.
        window_start: First bar index drawn on the chart.

    Returns:
        Swings that a preview is allowed to mark.
    """
    return [
        swing
        for swing in swings
        if swing.confirmation_index <= asof_index
        and window_start <= swing.pivot_index <= asof_index
    ]


def _record(
    swing_type: str,
    pivot_index: int,
    confirmation_index: int,
    pivot_price: float,
    confirmation_price: float,
    prominence_atr: float,
    prices: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    times: pd.Series,
    timeframe: str,
) -> Swing:
    """Build one swing using the ATR that was known at the pivot bar."""
    return Swing(
        swing_type=swing_type,
        pivot_index=int(pivot_index),
        confirmation_index=int(confirmation_index),
        pivot_price=float(pivot_price),
        confirmation_price=float(confirmation_price),
        atr_at_pivot=positive_atr(float(atr[pivot_index]), float(prices[pivot_index])),
        prominence_atr=float(prominence_atr),
        timeframe=timeframe,
        pivot_time=pd.Timestamp(times.iloc[pivot_index]),
        confirmation_time=pd.Timestamp(times.iloc[confirmation_index]),
    )


def bars_since_scale() -> float:
    """Denominator for the recency channel, fixed at the 192-bar window."""
    return float(np.log1p(WINDOW_BARS))
