"""Guards that stop pattern flags and future bars from entering features."""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from research.cpr_mtf.candidates import generate_candidates
from research.cpr_mtf.contract import FORBIDDEN_EXACT, FORBIDDEN_PREFIXES, SEQUENCE_CHANNELS
from research.cpr_mtf.swings import Swing
from research.cpr_mtf.windows import prepare_timeframe


def assert_feature_names(names: Sequence[str]) -> None:
    """Reject channels outside the sequence allow-list or on the denylist.

    Args:
        names: Channel names about to be placed in the sequence tensor.

    Raises:
        ValueError: If a name is unknown, forbidden, or repeated.
    """
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate feature channels: {list(names)}")
    blocked = forbidden_names(names)
    if blocked:
        raise ValueError(f"channels leak labels or forecast targets: {blocked}")
    unknown = [name for name in names if name not in SEQUENCE_CHANNELS]
    if unknown:
        raise ValueError(f"channels are outside the sequence allow-list: {unknown}")


def forbidden_names(names: Iterable[str]) -> list[str]:
    """Return names that match a forbidden prefix or an exact denylisted column.

    Args:
        names: Candidate channel names.

    Returns:
        The subset that must not enter the sequence tensor.
    """
    blocked: list[str] = []
    for name in names:
        if name in FORBIDDEN_EXACT or name.startswith(FORBIDDEN_PREFIXES):
            blocked.append(name)
    return blocked


def assert_causal_at(frame: pd.DataFrame, timeframe: str, index: int) -> None:
    """Require features, swings, and candidates at ``index`` to ignore later bars.

    Args:
        frame: OHLCV with a ``time`` column.
        timeframe: Timeframe passed to the feature builder.
        index: Bar whose outputs must stay fixed when later bars change.

    Raises:
        ValueError: If a feature, visible swing, or candidate changes.
        IndexError: If ``index`` is outside the frame.
    """
    if index < 0 or index >= len(frame):
        raise IndexError(f"index {index} is outside the frame of length {len(frame)}")
    if index + 1 >= len(frame):
        raise ValueError("perturbation requires bars after the inspected index")
    mutated = frame.copy()
    later = mutated.index[index + 1 :]
    for column in ("open", "high", "low", "close", "volume"):
        mutated.loc[later, column] = mutated.loc[later, column].astype(float) * 1.7
    original = prepare_timeframe(frame, timeframe)
    changed = prepare_timeframe(mutated, timeframe)
    left = original.matrix[: index + 1]
    right = changed.matrix[: index + 1]
    if not np.allclose(left, right, equal_nan=True):
        raise ValueError("sequence features changed when future bars were scaled")
    if not _same_swings(
        [swing for swing in original.swings if swing.confirmation_index <= index],
        [swing for swing in changed.swings if swing.confirmation_index <= index],
    ):
        raise ValueError("confirmed swings changed when future bars were scaled")
    original_ids = _candidate_rows(original.frame, original.swings, timeframe, index)
    changed_ids = _candidate_rows(changed.frame, changed.swings, timeframe, index)
    if original_ids != changed_ids:
        raise ValueError("candidates changed when future bars were scaled")


def _candidate_rows(
    frame: pd.DataFrame,
    swings: list[Swing],
    timeframe: str,
    index: int,
) -> list[tuple[str, tuple[float, ...]]]:
    """Identity and geometry of proposals at ``index``, sorted by id."""
    rows = []
    for candidate in generate_candidates(frame, swings, timeframe, index):
        rows.append((candidate.candidate_id, tuple(float(value) for value in candidate.features)))
    return sorted(rows)


def _same_swings(left: list[Swing], right: list[Swing]) -> bool:
    """Compare swing identity and prices, ignoring object identity."""
    if len(left) != len(right):
        return False
    for first, second in zip(left, right):
        if (
            first.swing_type != second.swing_type
            or first.pivot_index != second.pivot_index
            or first.confirmation_index != second.confirmation_index
        ):
            return False
        if not np.allclose(
            [first.pivot_price, first.confirmation_price, first.prominence_atr, first.atr_at_pivot],
            [
                second.pivot_price,
                second.confirmation_price,
                second.prominence_atr,
                second.atr_at_pivot,
            ],
        ):
            return False
    return True
