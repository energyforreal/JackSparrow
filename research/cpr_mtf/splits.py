"""Chronological splits with a purge of the longest 4-hour breakout label."""

from __future__ import annotations

import numpy as np

from research.cpr_mtf.contract import (
    PURGE_BARS,
    TRAIN_FRACTION,
    TRAIN_STRIDE,
    VAL_FRACTION,
)


def purged_split(
    end_indices: np.ndarray,
    *,
    purge: int = PURGE_BARS,
    train_fraction: float = TRAIN_FRACTION,
    val_fraction: float = VAL_FRACTION,
) -> dict[str, np.ndarray]:
    """Split end indices in time, leaving ``purge`` bars between partitions.

    Args:
        end_indices: Bar indices of window ends, sorted ascending.
        purge: Minimum bar gap between the last end of one split and the
            first end of the next. The default is 384 fifteen-minute bars.
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


def strided_ends(end_indices: np.ndarray, stride: int = TRAIN_STRIDE) -> np.ndarray:
    """Take every ``stride`` window end, preserving chronological order.

    Args:
        end_indices: Sorted bar indices.
        stride: Step between kept ends.

    Returns:
        Subsampled ends.

    Raises:
        ValueError: If ``stride`` is less than 1.
    """
    ends = np.asarray(end_indices, dtype=np.int64)
    if stride < 1:
        raise ValueError("stride must be positive")
    return ends[::stride]


def _require_gap(left: np.ndarray, right: np.ndarray, purge: int) -> None:
    """Raise when two partitions sit closer than ``purge`` bars."""
    gap = int(right[0]) - int(left[-1])
    if gap < purge:
        raise ValueError(f"split gap {gap} is shorter than the purge of {purge}")
