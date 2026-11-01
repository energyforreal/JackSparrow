"""Chronological splits with a purge of one full recognition window."""

from __future__ import annotations

import numpy as np

from research.recognition_15m.contract import (
    EVAL_STRIDE,
    PURGE_BARS,
    TRAIN_FRACTION,
    TRAIN_STRIDE,
    VAL_FRACTION,
    WINDOW_BARS,
)


def eligible_ends(n_bars: int, first_finite: int, window: int = WINDOW_BARS) -> np.ndarray:
    """Bar indices whose window lies entirely on finite feature rows.

    Args:
        n_bars: Length of the 15-minute series.
        first_finite: First bar with finite engineered features.
        window: Window length.

    Returns:
        Increasing end indices. Empty when the series is too short.
    """
    first_end = first_finite + window - 1
    if first_end >= n_bars:
        return np.empty(0, dtype=np.int64)
    return np.arange(first_end, n_bars, dtype=np.int64)


def purged_split(
    end_indices: np.ndarray,
    *,
    purge: int = PURGE_BARS,
    train_fraction: float = TRAIN_FRACTION,
    val_fraction: float = VAL_FRACTION,
) -> dict[str, np.ndarray]:
    """Split end indices in time, leaving ``purge`` bars between partitions.

    Args:
        end_indices: Bar indices of window ends, sorted ascending. The values
            are bar positions, so a gap of ``purge`` bars means the next
            window starts after the previous window ends.
        purge: Minimum bar gap between the last end of one split and the
            first end of the next.
        train_fraction: Share of ends assigned to train before the purge.
        val_fraction: Share of ends assigned to validation before the purge.

    Returns:
        Train, validation, and test end indices.

    Raises:
        ValueError: If a partition is empty or the gap is shorter than
            ``purge`` bars.
    """
    ends = np.asarray(end_indices, dtype=np.int64)
    if ends.size == 0 or np.any(np.diff(ends) < 0):
        raise ValueError("end indices must be non-empty and sorted")
    train_count = int(ends.size * train_fraction)
    val_count = int(ends.size * val_fraction)
    if train_count < 1 or val_count < 1:
        raise ValueError("series is too short to allocate train and validation")
    train = ends[:train_count]
    val_start = int(np.searchsorted(ends, int(train[-1]) + purge, side="left"))
    val = ends[val_start : val_start + val_count]
    if val.size == 0:
        raise ValueError("purge removed the validation partition")
    test_start = int(np.searchsorted(ends, int(val[-1]) + purge, side="left"))
    test = ends[test_start:]
    if test.size == 0:
        raise ValueError("purge removed the test partition")
    _require_gap(train, val, purge)
    _require_gap(val, test, purge)
    return {"train": train, "val": val, "test": test}


def _require_gap(left: np.ndarray, right: np.ndarray, purge: int) -> None:
    """Raise when two partitions share a window or sit closer than ``purge``."""
    gap = int(right[0]) - int(left[-1])
    if gap < purge:
        raise ValueError(f"split gap {gap} is shorter than the purge of {purge}")


def development_folds(
    train_ends: np.ndarray,
    val_ends: np.ndarray,
    *,
    folds: int = 3,
    purge: int = PURGE_BARS,
) -> list[dict[str, np.ndarray]]:
    """Build purged chronological folds inside the development span.

    Args:
        train_ends: Outer training window ends. The sealed test is absent.
        val_ends: Outer validation window ends. The sealed test is absent.
        folds: Number of validation blocks.
        purge: Minimum bar gap between a fold's train end and its validation.

    Returns:
        One mapping of ``train`` and ``val`` end indices per fold.

    Raises:
        ValueError: If a fold cannot keep the purge.
    """
    if folds < 1:
        raise ValueError("folds must be positive")
    dev = np.sort(np.unique(np.concatenate([
        np.asarray(train_ends, dtype=np.int64),
        np.asarray(val_ends, dtype=np.int64),
    ])))
    blocks = folds + 1
    if dev.size < blocks * 2:
        raise ValueError("development span is too short for purged folds")
    chunk = dev.size // blocks
    if chunk < 1:
        raise ValueError("development span is too short for purged folds")
    built: list[dict[str, np.ndarray]] = []
    for index in range(folds):
        val_pos = chunk * (index + 1)
        val_stop = chunk * (index + 2) if index < folds - 1 else dev.size
        val = dev[val_pos:val_stop]
        if val.size == 0:
            raise ValueError("a development fold has no validation windows")
        train = dev[dev <= int(val[0]) - purge]
        if train.size == 0:
            raise ValueError("a development fold has no training windows")
        _require_gap(train, val, purge)
        built.append({"train": train, "val": val})
    return built


def strided_ends(end_indices: np.ndarray, stride: int = TRAIN_STRIDE) -> np.ndarray:
    """Take every ``stride`` window end, preserving chronological order."""
    ends = np.asarray(end_indices, dtype=np.int64)
    if stride < 1:
        raise ValueError("stride must be positive")
    return ends[::stride]


def nonoverlapping_ends(
    end_indices: np.ndarray,
    stride: int = EVAL_STRIDE,
) -> np.ndarray:
    """Keep window ends that are at least ``stride`` bars apart.

    Args:
        end_indices: Sorted bar indices.
        stride: Minimum gap. The recognition window uses 48.

    Returns:
        Subset of ``end_indices``. The first end is kept.
    """
    ends = np.asarray(end_indices, dtype=np.int64)
    if ends.size == 0:
        return ends
    kept = [int(ends[0])]
    for end in ends[1:]:
        if int(end) - kept[-1] >= stride:
            kept.append(int(end))
    return np.asarray(kept, dtype=np.int64)
