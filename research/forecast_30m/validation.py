"""Chronological development splits. The holdout is not a fold."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from research.forecast_30m.contract import CALIBRATION_FRACTION, PURGE_BARS, WALKS


def assert_development_only(frame: pd.DataFrame, holdout_start: pd.Timestamp) -> None:
    """Refuse a training frame that contains a holdout timestamp.

    Args:
        frame: Candidate training rows. Must include ``time``.
        holdout_start: First holdout timestamp.

    Raises:
        RuntimeError: If any row is at or after the holdout.
    """
    stamps = pd.to_datetime(frame["time"], utc=True)
    if (stamps >= holdout_start).any():
        raise RuntimeError("refusing to train on holdout rows")


def assert_outside_embargo(
    frame: pd.DataFrame,
    embargo_start: pd.Timestamp,
    embargo_end: pd.Timestamp,
) -> None:
    """Refuse rows whose signal sits inside the spent holdout.

    Args:
        frame: Candidate rows. Must include ``time``.
        embargo_start: First embargo timestamp, inclusive.
        embargo_end: Last embargo timestamp, inclusive.

    Raises:
        RuntimeError: If any row is inside the embargo window.
    """
    stamps = pd.to_datetime(frame["time"], utc=True)
    inside = (stamps >= embargo_start) & (stamps <= embargo_end)
    if bool(inside.any()):
        raise RuntimeError("refusing embargoed rows")


def confirmation_mask(
    epoch_s: np.ndarray,
    *,
    confirmation_start: int,
    horizon_ok: np.ndarray | None = None,
) -> np.ndarray:
    """Rows whose signal is strictly after the frozen snapshot end.

    Args:
        epoch_s: Unix seconds.
        confirmation_start: Last snapshot timestamp, in Unix seconds. Signals
            must be strictly later.
        horizon_ok: Optional mask of rows that have every future bar.

    Returns:
        Boolean mask.
    """
    epochs = np.asarray(epoch_s, dtype=np.int64)
    mask = epochs > int(confirmation_start)
    if horizon_ok is not None:
        mask = mask & np.asarray(horizon_ok, dtype=bool)
    return mask


def development_blocks(
    bar_index: np.ndarray,
    *,
    calibration_fraction: float = CALIBRATION_FRACTION,
    horizon_bars: int = PURGE_BARS,
    folds: int = WALKS,
) -> dict[str, Any]:
    """Reserve a trailing calibration block, then cut purged walk-forward folds.

    Indices refer to ``bar_index``. A training row is kept only when its label
    ends strictly before the first bar of the next block.

    Args:
        bar_index: Original bar position of each supervised row, ascending.
        calibration_fraction: Share of rows reserved at the end.
        horizon_bars: Label length used as the purge width.
        folds: Expanding edges inside the fit prefix.

    Returns:
        Fit, calibration, and walk-forward index arrays.

    Raises:
        ValueError: If the series cannot support the blocks.
    """
    bars = np.asarray(bar_index, dtype=np.int64)
    n_rows = int(bars.shape[0])
    if n_rows < 200:
        raise ValueError(f"development series is too short: {n_rows}")
    calibration_rows = int(n_rows * float(calibration_fraction))
    if calibration_rows < 50:
        raise ValueError("calibration block is too small")
    calibration_start = n_rows - calibration_rows
    calibration_bar = int(bars[calibration_start])
    fit = np.flatnonzero(bars + int(horizon_bars) < calibration_bar)
    if fit.size < 100:
        raise ValueError("fit block is too small after the purge")
    edges = [int(fit.size * (step + 1) / int(folds)) for step in range(int(folds))]
    walk_folds = []
    for index in range(1, len(edges)):
        raw_train = fit[: edges[index - 1]]
        raw_val = fit[edges[index - 1] : edges[index]]
        if raw_train.size == 0 or raw_val.size == 0:
            continue
        val_bar = int(bars[int(raw_val[0])])
        train = raw_train[bars[raw_train] + int(horizon_bars) < val_bar]
        if train.size == 0:
            continue
        walk_folds.append({"train": train.astype(np.int64), "validation": raw_val.astype(np.int64)})
    if len(walk_folds) < 2:
        raise ValueError("walk-forward did not produce two folds")
    return {
        "fit": fit.astype(np.int64),
        "calibration": np.arange(calibration_start, n_rows, dtype=np.int64),
        "walk_forward": walk_folds,
        "horizon_bars": int(horizon_bars),
    }
