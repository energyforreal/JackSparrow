"""Guards that stop pattern flags and future bars from entering training."""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from research.recognition_15m.contract import (
    ALLOWED_CHANNELS,
    FORBIDDEN_EXACT,
    FORBIDDEN_PREFIXES,
)
from research.recognition_15m.features import add_engineered_features
from research.recognition_15m.labels import geometry_matrix, market_labels


def assert_feature_names(names: Sequence[str]) -> None:
    """Reject channels outside the allow-list or on the denylist.

    Args:
        names: Channel names about to be placed in the training tensor.

    Raises:
        ValueError: If a name is unknown, forbidden, or repeated.
    """
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate feature channels: {list(names)}")
    blocked = forbidden_names(names)
    if blocked:
        raise ValueError(f"channels leak labels or forecast targets: {blocked}")
    unknown = [name for name in names if name not in ALLOWED_CHANNELS]
    if unknown:
        raise ValueError(f"channels are outside the recognition allow-list: {unknown}")


def forbidden_names(names: Iterable[str]) -> list[str]:
    """Return names that match a forbidden prefix or an exact denylisted column."""
    blocked: list[str] = []
    for name in names:
        if name in FORBIDDEN_EXACT or name.startswith(FORBIDDEN_PREFIXES):
            blocked.append(name)
    return blocked


def assert_causal_at(frame: pd.DataFrame, index: int) -> None:
    """Require features and labels at ``index`` to ignore later bars.

    Args:
        frame: 15-minute OHLCV with a ``time`` column.
        index: Bar whose outputs must stay fixed when later bars change.

    Raises:
        ValueError: If a feature, geometric label, or market state changes.
        IndexError: If ``index`` is outside the frame.
    """
    if index < 0 or index >= len(frame):
        raise IndexError(f"index {index} is outside the frame of length {len(frame)}")
    mutated = frame.copy()
    later = mutated.index[index + 1 :]
    if len(later) == 0:
        raise ValueError("perturbation requires bars after the inspected index")
    for column in ("open", "high", "low", "close", "volume"):
        mutated.loc[later, column] = mutated.loc[later, column].astype(float) * 1.7

    original_features = add_engineered_features(frame)
    mutated_features = add_engineered_features(mutated)
    computed = [column for column in original_features.columns if column != "time"]
    left = original_features.iloc[: index + 1].loc[:, computed].to_numpy(dtype=np.float64)
    right = mutated_features.iloc[: index + 1].loc[:, computed].to_numpy(dtype=np.float64)
    if not np.allclose(left, right, equal_nan=True):
        raise ValueError("engineered features changed when future bars were scaled")

    original_geometry = _geometry_from(original_features)
    mutated_geometry = _geometry_from(mutated_features)
    if not np.array_equal(original_geometry[: index + 1], mutated_geometry[: index + 1]):
        raise ValueError("geometric labels changed when future bars were scaled")

    original_state, original_tag = _market_from(original_features)
    mutated_state, mutated_tag = _market_from(mutated_features)
    if not np.array_equal(original_state[: index + 1], mutated_state[: index + 1]):
        raise ValueError("market state changed when future bars were scaled")
    if not np.array_equal(original_tag[: index + 1], mutated_tag[: index + 1]):
        raise ValueError("structure tag changed when future bars were scaled")


def _geometry_from(features: pd.DataFrame) -> np.ndarray:
    """Geometric labels from a feature frame's prices and ATR."""
    return geometry_matrix(
        features["open"].to_numpy(dtype=np.float64),
        features["high"].to_numpy(dtype=np.float64),
        features["low"].to_numpy(dtype=np.float64),
        features["close"].to_numpy(dtype=np.float64),
        features["atr"].to_numpy(dtype=np.float64),
    )


def _market_from(features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Market state and tag from a feature frame's prices and ATR."""
    return market_labels(
        features["high"].to_numpy(dtype=np.float64),
        features["low"].to_numpy(dtype=np.float64),
        features["close"].to_numpy(dtype=np.float64),
        features["atr"].to_numpy(dtype=np.float64),
    )
