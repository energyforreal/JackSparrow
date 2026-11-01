"""Window tensors for the recognition track.

The rule card is built so it can be audited, then kept off the feature tensor.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from research.recognition_15m.contract import (
    ENGINEERED_CHANNELS,
    RAW_CHANNELS,
    RULE_CARD_COLUMNS,
    WINDOW_BARS,
)
from research.recognition_15m.features import add_engineered_features, first_finite_bar, safe_scale
from research.recognition_15m.integrity import assert_feature_names
from research.recognition_15m.labels import build_rule_card, geometry_matrix, market_labels
from research.recognition_15m.splits import eligible_ends, purged_split


class ChannelScaler:
    """Per-channel mean and standard deviation fit on training windows only."""

    def __init__(self) -> None:
        self.mean = np.zeros(1, dtype=np.float32)
        self.std = np.ones(1, dtype=np.float32)

    def fit(self, windows: np.ndarray) -> "ChannelScaler":
        """Fit on an array of shape ``(n, time, channels)``.

        Args:
            windows: Training windows.

        Returns:
            This scaler.
        """
        if windows.ndim != 3:
            raise ValueError("windows must have shape (n, time, channels)")
        mean = windows.mean(axis=(0, 1)).astype(np.float32)
        std = windows.std(axis=(0, 1)).astype(np.float32)
        std = np.where(std < 1e-6, np.float32(1.0), std)
        self.mean = mean
        self.std = std.astype(np.float32)
        return self

    def transform(self, windows: np.ndarray) -> np.ndarray:
        """Standardize with the training mean and standard deviation."""
        return ((windows - self.mean) / self.std).astype(np.float32)


def prepare_series(frame: pd.DataFrame) -> dict[str, object]:
    """Compute features, labels, the rule card, and purged splits.

    Args:
        frame: Completed 15-minute OHLCV.

    Returns:
        Mapping with feature frame, geometry, market labels, rule card, and
        split end indices. The rule card is not a feature matrix.

    Raises:
        ValueError: If the rule card shares a column with the model channels.
    """
    features = add_engineered_features(frame)
    open_ = features["open"].to_numpy(dtype=np.float64)
    high = features["high"].to_numpy(dtype=np.float64)
    low = features["low"].to_numpy(dtype=np.float64)
    close = features["close"].to_numpy(dtype=np.float64)
    atr = features["atr"].to_numpy(dtype=np.float64)
    geometry = geometry_matrix(open_, high, low, close, atr)
    states, tags = market_labels(high, low, close, atr)
    rule_card = build_rule_card(features, atr, geometry)
    leaked = set(rule_card.columns) & (set(ENGINEERED_CHANNELS) | set(RAW_CHANNELS))
    if leaked:
        raise ValueError(f"rule card columns entered the feature set: {sorted(leaked)}")
    assert_feature_names(RAW_CHANNELS)
    assert_feature_names(ENGINEERED_CHANNELS)
    ends = eligible_ends(len(features), first_finite_bar(features))
    splits = purged_split(ends)
    return {
        "features": features,
        "geometry": geometry,
        "states": states,
        "tags": tags,
        "rule_card": rule_card,
        "splits": splits,
    }


def stack_windows(
    prepared: Mapping[str, object],
    end_indices: np.ndarray,
    mode: str,
) -> dict[str, np.ndarray]:
    """Stack a causal window for each end index.

    Args:
        prepared: Output of :func:`prepare_series`.
        end_indices: Window end bar indices.
        mode: ``raw`` or ``engineered``.

    Returns:
        ``features`` of shape ``(n, 48, channels)``, ``geometry`` of shape
        ``(n, 48, classes)``, and integer ``state`` and ``tag`` vectors.

    Raises:
        ValueError: If ``mode`` is unknown or a window is non-finite.
    """
    ends = np.asarray(end_indices, dtype=np.int64)
    features = prepared["features"]
    if not isinstance(features, pd.DataFrame):
        raise TypeError("prepared series is missing the feature frame")
    if mode == "raw":
        windows = _raw_windows(features, ends)
        channels = RAW_CHANNELS
    elif mode == "engineered":
        windows = _engineered_windows(features, ends)
        channels = ENGINEERED_CHANNELS
    else:
        raise ValueError(f"unknown feature mode: {mode}")
    assert_feature_names(channels)
    if not np.isfinite(windows).all():
        raise ValueError(f"{mode} windows contain non-finite values")
    geometry = np.asarray(prepared["geometry"])
    grid = ends[:, None] - (WINDOW_BARS - 1) + np.arange(WINDOW_BARS)[None, :]
    return {
        "features": windows,
        "geometry": geometry[grid].astype(np.float32),
        "state": np.asarray(prepared["states"])[ends].astype(np.int64),
        "tag": np.asarray(prepared["tags"])[ends].astype(np.int64),
        "channels": np.asarray(channels),
    }


def _engineered_windows(features: pd.DataFrame, ends: np.ndarray) -> np.ndarray:
    """Slice engineered channels into ``(n, time, channels)`` windows."""
    matrix = features.loc[:, list(ENGINEERED_CHANNELS)].to_numpy(dtype=np.float32)
    grid = ends[:, None] - (WINDOW_BARS - 1) + np.arange(WINDOW_BARS)[None, :]
    return matrix[grid]


def _raw_windows(features: pd.DataFrame, ends: np.ndarray) -> np.ndarray:
    """Scale raw OHLCV by the ATR and volume baseline at the window end."""
    open_ = features["open"].to_numpy(dtype=np.float64)
    high = features["high"].to_numpy(dtype=np.float64)
    low = features["low"].to_numpy(dtype=np.float64)
    close = features["close"].to_numpy(dtype=np.float64)
    volume = features["volume"].to_numpy(dtype=np.float64)
    atr = features["atr"].to_numpy(dtype=np.float64)
    baseline = features["volume_baseline"].to_numpy(dtype=np.float64)
    starts = ends - (WINDOW_BARS - 1)
    grid = starts[:, None] + np.arange(WINDOW_BARS)[None, :]
    atr_ref = np.array([safe_scale(float(atr[end])) for end in ends], dtype=np.float64)
    vol_ref = np.array(
        [safe_scale(float(baseline[end])) for end in ends],
        dtype=np.float64,
    )
    reference = close[starts]
    prices = (
        np.stack([open_[grid], high[grid], low[grid], close[grid]], axis=-1)
        - reference[:, None, None]
    ) / atr_ref[:, None, None]
    volume_ratio = volume[grid] / vol_ref[:, None]
    return np.concatenate(
        [prices.astype(np.float32), volume_ratio.astype(np.float32)[..., None]],
        axis=-1,
    )


def rule_card_is_separate(prepared: Mapping[str, object]) -> bool:
    """Return True when the rule card shares no column with model channels."""
    card = prepared["rule_card"]
    if not isinstance(card, pd.DataFrame):
        return False
    if list(card.columns) != list(RULE_CARD_COLUMNS):
        return False
    return not (set(card.columns) & (set(RAW_CHANNELS) | set(ENGINEERED_CHANNELS)))
