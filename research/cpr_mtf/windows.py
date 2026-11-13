"""As-of alignment and 192-bar windows with 48- and 96-bar suffixes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from research.cpr_mtf.contract import (
    BAR_MINUTES,
    FIRST_FINITE_BAR,
    SEQUENCE_CHANNELS,
    SUFFIX_BARS,
    TIMEFRAMES,
    WINDOW_BARS,
)
from research.cpr_mtf.features import add_sequence_features
from research.cpr_mtf.swings import Swing

@dataclass
class PreparedSeries:
    """One timeframe after causal feature construction.

    Attributes:
        timeframe: ``15m``, ``1h``, or ``4h``.
        frame: OHLCV, ATR, and the 20 sequence channels.
        swings: Confirmed swings for the whole series.
        matrix: Sequence channels as ``(n, 20)``.
    """

    timeframe: str
    frame: pd.DataFrame
    swings: list[Swing]
    matrix: np.ndarray


def prepare_timeframe(frame: pd.DataFrame, timeframe: str) -> PreparedSeries:
    """Build features, swings, and the sequence matrix for one timeframe.

    Args:
        frame: Completed OHLCV for ``timeframe``.
        timeframe: ``15m``, ``1h``, or ``4h``.

    Returns:
        Prepared series whose matrix column order is ``SEQUENCE_CHANNELS``.
    """
    featured, swings = add_sequence_features(frame, timeframe)
    matrix = featured.loc[:, list(SEQUENCE_CHANNELS)].to_numpy(dtype=np.float64)
    return PreparedSeries(
        timeframe=timeframe,
        frame=featured,
        swings=swings,
        matrix=matrix,
    )


def bar_end(open_time: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    """Return the exclusive end of a bar that opens at ``open_time``.

    Args:
        open_time: Bucket open timestamp.
        timeframe: Bar size.

    Returns:
        UTC timestamp when the bar is complete.
    """
    stamp = pd.Timestamp(open_time)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp + pd.Timedelta(minutes=BAR_MINUTES[timeframe])


def last_complete_index(
    frame: pd.DataFrame,
    timeframe: str,
    asof_end: pd.Timestamp,
) -> int | None:
    """Return the last bar whose bucket end is at or before ``asof_end``.

    Args:
        frame: Completed bars with a ``time`` column of bucket opens.
        timeframe: Bar size used to compute bucket ends.
        asof_end: Prediction clock.

    Returns:
        Row position, or ``None`` when every bar is still incomplete.
    """
    if frame.empty:
        return None
    clock = pd.Timestamp(asof_end)
    if clock.tzinfo is None:
        clock = clock.tz_localize("UTC")
    else:
        clock = clock.tz_convert("UTC")
    opens = pd.to_datetime(frame["time"], utc=True)
    ends = opens + pd.Timedelta(minutes=BAR_MINUTES[timeframe])
    eligible = np.flatnonzero((ends <= clock).to_numpy())
    if len(eligible) == 0:
        return None
    return int(eligible[-1])


def slice_window(matrix: np.ndarray, end_index: int, length: int = WINDOW_BARS) -> np.ndarray:
    """Copy the ``length`` rows ending at ``end_index``.

    Args:
        matrix: Full sequence matrix.
        end_index: Inclusive last row.
        length: Window length.

    Returns:
        Array of shape ``(length, channels)``.

    Raises:
        ValueError: If the window would start before row 0 or leave the matrix.
    """
    if end_index < 0 or end_index >= len(matrix):
        raise ValueError(f"end index {end_index} is outside the series")
    start = end_index - length + 1
    if start < 0:
        raise ValueError(f"window of {length} bars starts before the series")
    return np.array(matrix[start : end_index + 1], dtype=np.float64, copy=True)


def window_suffixes(window: np.ndarray) -> dict[int, np.ndarray]:
    """Return the 48, 96, and 192 row suffixes of one 192-bar window.

    Args:
        window: Array whose first axis is 192 bars.

    Returns:
        Copies keyed by suffix length. The 192-bar value is the full window.

    Raises:
        ValueError: If ``window`` is not 192 bars long.
    """
    if window.shape[0] != WINDOW_BARS:
        raise ValueError(f"expected {WINDOW_BARS} rows, found {window.shape[0]}")
    return {length: np.array(window[-length:], copy=True) for length in SUFFIX_BARS}


def eligible_ends(
    n_bars: int,
    first_finite: int = FIRST_FINITE_BAR,
    window: int = WINDOW_BARS,
) -> np.ndarray:
    """Bar indices whose 192-bar window starts on a finite feature row.

    Args:
        n_bars: Length of the timeframe series.
        first_finite: First row with finite ATR and volume baseline.
        window: Window length.

    Returns:
        Increasing end indices. Empty when the series is too short.
    """
    first_end = first_finite + window - 1
    if first_end >= n_bars:
        return np.empty(0, dtype=np.int64)
    return np.arange(first_end, n_bars, dtype=np.int64)


def finite_window(matrix: np.ndarray, end_index: int) -> bool:
    """Return True when the 192-bar window ending at ``end_index`` is finite."""
    if end_index < WINDOW_BARS - 1 or end_index >= len(matrix):
        return False
    window = matrix[end_index - WINDOW_BARS + 1 : end_index + 1]
    return bool(np.isfinite(window).all())


def build_sample(
    prepared: dict[str, PreparedSeries],
    asof_end: pd.Timestamp,
) -> dict[str, object]:
    """Align every timeframe to one clock and build proposals at that clock.

    Args:
        prepared: Feature series keyed by timeframe.
        asof_end: Prediction clock. Higher-timeframe bars must have ended.

    Returns:
        Windows, suffixes, padded geometry, proposal metadata, and pairs.
        Preview charts and any later training batch both call this function.

    Raises:
        ValueError: If a timeframe lacks a finite 192-bar window.
    """
    from research.cpr_mtf.candidates import (
        generate_candidates,
        proposal_record,
        propose_pairs,
        stack_candidates,
    )

    windows: dict[str, np.ndarray] = {}
    suffixes: dict[str, dict[int, np.ndarray]] = {}
    candidates: dict[str, list] = {}
    ends: dict[str, int] = {}
    for timeframe in TIMEFRAMES:
        series = prepared[timeframe]
        end = last_complete_index(series.frame, timeframe, asof_end)
        if end is None or not finite_window(series.matrix, end):
            raise ValueError(f"{timeframe} has no finite 192-bar window at {asof_end}")
        window = slice_window(series.matrix, end)
        windows[timeframe] = window
        suffixes[timeframe] = window_suffixes(window)
        candidates[timeframe] = generate_candidates(
            series.frame, series.swings, timeframe, end
        )
        ends[timeframe] = end
    features, mask, ordered = stack_candidates(candidates)
    return {
        "asof_end": pd.Timestamp(asof_end),
        "end_index": ends,
        "windows": windows,
        "suffixes": suffixes,
        "candidate_features": features,
        "candidate_mask": mask,
        "proposals": [proposal_record(candidate) for candidate in ordered],
        "pairs": propose_pairs(ordered),
        "candidates": candidates,
    }
