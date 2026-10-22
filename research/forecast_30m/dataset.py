"""One supervised row per eligible signal candle."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.forecast_30m.contract import FEATURE_COLUMNS, FEATURE_VERSION, LABEL_VERSION
from research.forecast_30m.contract_v4 import (
    FEATURE_COLUMNS as FEATURE_COLUMNS_V4,
    FEATURE_VERSION as FEATURE_VERSION_V4,
    LABEL_VERSION as LABEL_VERSION_V4,
)
from research.forecast_30m.contract_v3 import (
    CUSUM_THRESHOLD,
    ENTRY,
    LABEL_VERSION as LABEL_VERSION_V3,
    SL_PCT,
    TP_PCT,
)
from research.forecast_30m.features import add_features
from research.forecast_30m.integrity import bar_seconds, to_epoch_seconds
from research.forecast_30m.labels import (
    attach_targets,
    cusum_event_mask,
    development_supervised_mask,
)
from research.forecast_30m.validation import confirmation_mask


def build_supervised_frames(
    frame: pd.DataFrame,
    *,
    theta: float | None,
    tp_mult: float | None,
    sl_mult: float | None,
    holdout_start: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build development and holdout modeling frames.

    Args:
        frame: Full audited OHLCV series.
        theta: Frozen neutral-band multiple, or ``None`` when direction is blocked.
        tp_mult: Frozen take-profit multiple, or ``None`` when barriers are blocked.
        sl_mult: Frozen stop multiple.
        holdout_start: First holdout timestamp. Paths that touch it leave development.

    Returns:
        Development rows, then holdout rows. Both are time-ordered.
    """
    labeled = attach_targets(
        add_features(frame),
        theta=theta,
        tp_mult=tp_mult,
        sl_mult=sl_mult,
    )
    labeled.insert(0, "bar_index", np.arange(len(labeled), dtype=np.int64))
    epochs = to_epoch_seconds(labeled["time"])
    holdout_epoch = int(pd.Timestamp(holdout_start).timestamp())
    horizon_ok = labeled["horizon_ok"].to_numpy(dtype=bool)
    ready = labeled["label_row_ok"].to_numpy(dtype=bool) & labeled["feature_row_ok"].to_numpy(
        dtype=bool
    )
    development = development_supervised_mask(
        epochs,
        holdout_start=holdout_epoch,
        bar_length=bar_seconds(),
        horizon_ok=horizon_ok,
    )
    holdout = (epochs >= holdout_epoch) & ready
    development = development & ready
    columns = _model_columns(labeled)
    dev_frame = labeled.loc[development, columns].reset_index(drop=True)
    hold_frame = labeled.loc[holdout, columns].reset_index(drop=True)
    for split in (dev_frame, hold_frame):
        split["feature_version"] = FEATURE_VERSION
        split["label_version"] = LABEL_VERSION
    return dev_frame, hold_frame


def _model_columns(frame: pd.DataFrame) -> list[str]:
    labels = [
        "atr",
        "neutral_band",
        "y_direction",
        "forward_return_24",
        "forward_log_return_24",
        "long_path_code",
        "short_path_code",
        "long_tp_first_24",
        "short_tp_first_24",
        "tp_pct",
        "sl_pct",
    ]
    leading = ["bar_index", "time"]
    present = [column for column in labels if column in frame.columns]
    return leading + list(FEATURE_COLUMNS) + present


def build_direction_frames(
    frame: pd.DataFrame,
    *,
    theta: float,
    development_end: pd.Timestamp,
) -> pd.DataFrame:
    """Build development rows for the v4 direction head.

    Args:
        frame: Original OHLCV snapshot. Confirmation bars must not be present.
        theta: Frozen class-floor theta.
        development_end: First embargo timestamp. Labels that touch it leave.

    Returns:
        Time-ordered development rows with v4 features and ``y_direction``.
    """
    labeled = attach_targets(
        add_features(frame, feature_columns=FEATURE_COLUMNS_V4),
        theta=theta,
        tp_mult=None,
        sl_mult=None,
        entry="next_open",
    )
    labeled.insert(0, "bar_index", np.arange(len(labeled), dtype=np.int64))
    epochs = to_epoch_seconds(labeled["time"])
    development_epoch = int(pd.Timestamp(development_end).timestamp())
    ready = labeled["label_row_ok"].to_numpy(dtype=bool) & labeled["feature_row_ok"].to_numpy(
        dtype=bool
    )
    direction_ok = labeled["y_direction"].to_numpy(dtype=np.int64) >= 0
    development = development_supervised_mask(
        epochs,
        holdout_start=development_epoch,
        bar_length=bar_seconds(),
        horizon_ok=labeled["horizon_ok"].to_numpy(dtype=bool),
    )
    keep = development & ready & direction_ok
    columns = (
        ["bar_index", "time"]
        + list(FEATURE_COLUMNS_V4)
        + ["atr", "neutral_band", "y_direction", "forward_return_24"]
    )
    out = labeled.loc[keep, columns].reset_index(drop=True)
    out["feature_version"] = FEATURE_VERSION_V4
    out["label_version"] = LABEL_VERSION_V4
    return out


def build_event_frames(
    frame: pd.DataFrame,
    *,
    development_end: pd.Timestamp,
    snapshot_end: pd.Timestamp,
    tp_pct: float = TP_PCT,
    sl_pct: float = SL_PCT,
    cusum_threshold: float = CUSUM_THRESHOLD,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build CUSUM-event frames for development, embargo, and confirmation.

    Embargo rows are returned so callers can prove they were not scored. They
    are not a training split.

    Args:
        frame: Full OHLCV series, including any appended confirmation bars.
        development_end: First spent-holdout timestamp. Development labels end
            strictly before it.
        snapshot_end: Last bar of the original snapshot. Confirmation signals
            are strictly after it.
        tp_pct: Take-profit as a fraction of the next-bar fill.
        sl_pct: Stop as a fraction of the fill.
        cusum_threshold: Symmetric CUSUM height on log returns.

    Returns:
        Development events, embargo events, confirmation events.
    """
    featured = add_features(frame)
    events = cusum_event_mask(
        featured["close"].to_numpy(dtype=np.float64),
        threshold=cusum_threshold,
    )
    labeled = attach_targets(
        featured,
        theta=None,
        tp_mult=None,
        sl_mult=None,
        entry=ENTRY,
        tp_pct_fixed=tp_pct,
        sl_pct_fixed=sl_pct,
        event_mask=events,
    )
    labeled.insert(0, "bar_index", np.arange(len(labeled), dtype=np.int64))
    labeled["cusum_event"] = events
    epochs = to_epoch_seconds(labeled["time"])
    development_epoch = int(pd.Timestamp(development_end).timestamp())
    snapshot_epoch = int(pd.Timestamp(snapshot_end).timestamp())
    horizon_ok = labeled["horizon_ok"].to_numpy(dtype=bool)
    ready = labeled["label_row_ok"].to_numpy(dtype=bool) & labeled["feature_row_ok"].to_numpy(
        dtype=bool
    )
    development = development_supervised_mask(
        epochs,
        holdout_start=development_epoch,
        bar_length=bar_seconds(),
        horizon_ok=horizon_ok,
    )
    confirmation = confirmation_mask(
        epochs,
        confirmation_start=snapshot_epoch,
        horizon_ok=horizon_ok,
    )
    embargo = (epochs >= development_epoch) & (epochs <= snapshot_epoch)
    development = development & ready
    confirmation = confirmation & ready
    embargo = embargo & events
    columns = _model_columns(labeled)
    extra = [column for column in ("cusum_event", "entry_rule") if column in labeled.columns]
    columns = columns + [column for column in extra if column not in columns]
    dev_frame = labeled.loc[development, columns].reset_index(drop=True)
    embargo_frame = labeled.loc[embargo, columns].reset_index(drop=True)
    conf_frame = labeled.loc[confirmation, columns].reset_index(drop=True)
    for split in (dev_frame, embargo_frame, conf_frame):
        split["feature_version"] = FEATURE_VERSION
        split["label_version"] = LABEL_VERSION_V3
    return dev_frame, embargo_frame, conf_frame
