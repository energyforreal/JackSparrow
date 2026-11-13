"""Chronological splits with an embargo around overlapping trade outcomes."""

from __future__ import annotations

from typing import Iterator


def chronological_bounds(
    row_count: int,
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
) -> tuple[int, int, int]:
    """Return train end, validation end, and the sealed start.

    Args:
        row_count: Number of rows in time order.
        train_fraction: Share used to fit.
        validation_fraction: Share used to tune and calibrate. The remainder
            is the sealed test.

    Returns:
        ``(train_end, validation_end, sealed_start)``. ``sealed_start`` equals
        ``validation_end``.

    Raises:
        ValueError: If the fractions do not leave a sealed tail.
    """
    if row_count < 3:
        raise ValueError("need at least 3 rows to split")
    if train_fraction <= 0.0 or validation_fraction <= 0.0:
        raise ValueError("train and validation fractions must be positive")
    if train_fraction + validation_fraction >= 1.0:
        raise ValueError("fractions must leave a sealed tail")
    train_end = max(1, int(row_count * train_fraction))
    validation_end = max(train_end + 1, int(row_count * (train_fraction + validation_fraction)))
    validation_end = min(validation_end, row_count - 1)
    return train_end, validation_end, validation_end


def apply_embargo(train_indexes: list[int], validation_start: int, embargo: int) -> list[int]:
    """Drop training rows that sit inside the embargo before validation.

    Args:
        train_indexes: Candidate training positions.
        validation_start: First validation row.
        embargo: Bars to drop before ``validation_start``. Use at least the
            longest holding period so a trade opened in train cannot close
            inside validation.

    Returns:
        Training positions that end before the embargo.
    """
    cutoff = validation_start - max(0, int(embargo))
    return [index for index in train_indexes if index < cutoff]


def purged_folds(
    row_count: int,
    *,
    n_splits: int = 3,
    embargo: int = 24,
) -> Iterator[tuple[list[int], list[int]]]:
    """Yield expanding walk-forward folds on a chronological frame.

    Args:
        row_count: Number of rows.
        n_splits: Validation blocks carved from the development span. The last
            15 percent of rows is not yielded.
        embargo: Bars removed from the end of each training side.

    Yields:
        ``(train_indexes, validation_indexes)``.

    Raises:
        ValueError: If the frame is too short for the requested folds.
    """
    _, _, sealed = chronological_bounds(row_count)
    development = sealed
    if development < n_splits * 2:
        raise ValueError("not enough development rows for the requested folds")
    block = max(1, development // (n_splits + 1))
    for fold in range(n_splits):
        validation_start = block * (fold + 1)
        validation_end = min(development, validation_start + block)
        if validation_end <= validation_start:
            continue
        train = apply_embargo(list(range(validation_start)), validation_start, embargo)
        validation = list(range(validation_start, validation_end))
        if not train or not validation:
            continue
        yield train, validation
