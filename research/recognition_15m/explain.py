"""Train-only correlation and TreeSHAP for the recognition features.

Neither audit adds a column. Both refuse names outside the allow-list.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from scipy.stats import spearmanr
from xgboost import XGBClassifier

from research.recognition_15m.contract import (
    CORRELATION_FLAG,
    ENGINEERED_CHANNELS,
    GEOMETRIC_CLASSES,
    SEED,
    SHAP_SAMPLE,
    WINDOW_BARS,
    XGB_ESTIMATORS,
    XGB_MAX_DEPTH,
)
from research.recognition_15m.integrity import assert_feature_names


def spearman_report(
    features: np.ndarray,
    geometry: np.ndarray,
    state: np.ndarray,
    channels: Sequence[str] = ENGINEERED_CHANNELS,
    *,
    flag_at: float = CORRELATION_FLAG,
) -> dict[str, Any]:
    """Spearman correlation of allowed channels with recognition labels.

    Args:
        features: Training windows, shape ``(n, time, channels)``.
        geometry: Per-bar geometric labels aligned with ``features``.
        state: Window market-state codes.
        channels: Channel names. Must be the recognition allow-list.
        flag_at: Absolute correlation that is reported as high.

    Returns:
        Pair rows and the high-correlation subset. A high value means the
        geometry rule is visible in an allowed channel. It does not add a
        feature.
    """
    assert_feature_names(tuple(channels))
    last = features[:, -1, :]
    pooled = features.mean(axis=1)
    last_labels = geometry[:, -1, :]
    presence = (geometry.max(axis=1) >= 0.5).astype(np.float64)
    rows: list[dict[str, Any]] = []
    for channel_index, channel in enumerate(channels):
        for class_index, class_name in enumerate(GEOMETRIC_CLASSES):
            rows.append(
                _pair(
                    channel,
                    class_name,
                    "last_bar",
                    _spearman(last[:, channel_index], last_labels[:, class_index]),
                    flag_at,
                )
            )
            rows.append(
                _pair(
                    channel,
                    class_name,
                    "window_mean",
                    _spearman(pooled[:, channel_index], presence[:, class_index]),
                    flag_at,
                )
            )
        rows.append(
            _pair(
                channel,
                "market_state",
                "last_bar",
                _spearman(last[:, channel_index], state.astype(np.float64)),
                flag_at,
            )
        )
        rows.append(
            _pair(
                channel,
                "market_state",
                "window_mean",
                _spearman(pooled[:, channel_index], state.astype(np.float64)),
                flag_at,
            )
        )
    flagged = [row for row in rows if row["flagged"]]
    return {"threshold": float(flag_at), "pairs": rows, "flagged": flagged}


def presence_shap(
    features: np.ndarray,
    geometry: np.ndarray,
    channels: Sequence[str] = ENGINEERED_CHANNELS,
    *,
    sample_size: int = SHAP_SAMPLE,
    n_estimators: int = XGB_ESTIMATORS,
    seed: int = SEED,
) -> dict[str, Any]:
    """TreeSHAP of the presence baseline, summed back to input channels.

    Args:
        features: Development windows the trees are fit on.
        geometry: Geometric labels for those windows.
        channels: Allow-listed channel names.
        sample_size: Maximum windows passed to the explainer.
        n_estimators: Trees per family.
        seed: Sample and tree seed.

    Returns:
        Mean absolute SHAP by channel for each family that had both classes.
    """
    assert_feature_names(tuple(channels))
    import shap

    flat = features.reshape(len(features), -1)
    presence = (geometry.max(axis=1) >= 0.5).astype(np.int64)
    rng = np.random.default_rng(seed)
    take = min(int(sample_size), len(features))
    chosen = np.sort(rng.choice(len(features), size=take, replace=False))
    explain_rows = flat[chosen]
    per_class: dict[str, Any] = {}
    for class_index, name in enumerate(GEOMETRIC_CLASSES):
        labels = presence[:, class_index]
        positives = int(labels.sum())
        negatives = int(len(labels) - positives)
        if positives == 0 or negatives == 0:
            per_class[name] = {"skipped": True}
            continue
        model = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=XGB_MAX_DEPTH,
            learning_rate=0.1,
            objective="binary:logistic",
            eval_metric="logloss",
            scale_pos_weight=float(negatives) / float(positives),
            tree_method="hist",
            n_jobs=1,
            random_state=seed,
        )
        model.fit(flat, labels)
        explainer = shap.TreeExplainer(model)
        values = explainer.shap_values(explain_rows)
        width = int(explain_rows.shape[1])
        summary = aggregate_shap_to_channels(
            _positive_shap(values, width),
            n_time=WINDOW_BARS,
            n_channels=len(channels),
        )
        per_class[name] = {
            "skipped": False,
            "channels": {
                channel: float(summary[index]) for index, channel in enumerate(channels)
            },
        }
    return {"sample_size": int(take), "per_class": per_class}


def aggregate_shap_to_channels(
    flat_importance: np.ndarray,
    *,
    n_time: int,
    n_channels: int,
) -> np.ndarray:
    """Sum a flattened window explanation back onto the channel axis.

    Args:
        flat_importance: Mean absolute SHAP with one value per flattened input.
        n_time: Bars in the window.
        n_channels: Channels per bar.

    Returns:
        Nonnegative importance per channel.
    """
    flat = np.asarray(flat_importance, dtype=np.float64).reshape(-1)
    expected = int(n_time) * int(n_channels)
    if flat.size != expected:
        raise ValueError(f"expected {expected} SHAP values, got {flat.size}")
    return np.abs(flat.reshape(int(n_time), int(n_channels))).sum(axis=0)


def _positive_shap(values: object, width: int) -> np.ndarray:
    """Reduce TreeSHAP output to one mean-absolute vector of ``width``."""
    if isinstance(values, list):
        values = values[-1]
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1 and array.size == width:
        return np.abs(array)
    if array.shape[-1] == width:
        axes = tuple(range(array.ndim - 1))
        return np.mean(np.abs(array), axis=axes)
    raise ValueError(f"cannot align SHAP shape {array.shape} to width {width}")


def _pair(
    channel: str,
    label: str,
    reduction: str,
    coefficient: float,
    flag_at: float,
) -> dict[str, Any]:
    """One correlation row."""
    return {
        "channel": channel,
        "label": label,
        "reduction": reduction,
        "spearman": float(coefficient),
        "flagged": bool(abs(coefficient) >= flag_at),
    }


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    """Spearman correlation, or zero when either side has no variation."""
    mask = np.isfinite(left) & np.isfinite(right)
    if int(mask.sum()) < 8:
        return 0.0
    lhs = np.asarray(left[mask], dtype=np.float64)
    rhs = np.asarray(right[mask], dtype=np.float64)
    if float(np.std(lhs)) < 1e-12 or float(np.std(rhs)) < 1e-12:
        return 0.0
    result = spearmanr(lhs, rhs)
    coefficient = getattr(result, "statistic", None)
    if coefficient is None:
        coefficient = result[0]
    if coefficient is None or not np.isfinite(float(coefficient)):
        return 0.0
    return float(coefficient)
