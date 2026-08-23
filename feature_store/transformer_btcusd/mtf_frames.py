"""Independent multi-timeframe OHLCV construction and causal as-of alignment.

10m is built from two consecutive closed 5m bars outside the model. Higher TFs
are never resampled inside the encoder; they are joined with merge_asof on
fully closed bar close-time.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    FUSION_INPUT_RESOLUTIONS,
    RESOLUTION_MINUTES,
)


def _ensure_time_column(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with UTC ``time`` plus original columns."""
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    elif "timestamp" in out.columns:
        ts = out["timestamp"]
        if pd.api.types.is_numeric_dtype(ts):
            out["time"] = pd.to_datetime(ts, unit="s", utc=True)
        else:
            out["time"] = pd.to_datetime(ts, utc=True)
    else:
        raise ValueError("OHLCV frame requires time or timestamp")
    return out.sort_values("time").reset_index(drop=True)


def bar_close_time(open_time: pd.Series, resolution_minutes: int) -> pd.Series:
    """Candle close time from open time (Delta bars are labeled at open)."""
    return pd.to_datetime(open_time, utc=True) + pd.Timedelta(
        minutes=int(resolution_minutes)
    )


def build_10m_ohlcv_from_5m(df5m: pd.DataFrame) -> pd.DataFrame:
    """Construct an independent 10m OHLCV series from two closed 5m bars.

    Aggregation is exchange-aligned (left-closed, left-labeled): each 10m bar
    covers ``[T, T+10m)`` and uses the two 5m opens at T and T+5m. High/low
    are the true extrema of those source bars. This is done *outside* the
    model — the encoder never resamples 5m on the forward pass.
    """
    src = _ensure_time_column(df5m)
    required = ("open", "high", "low", "close", "volume")
    missing = [c for c in required if c not in src.columns]
    if missing:
        raise ValueError(f"5m OHLCV missing columns: {missing}")
    if src.empty:
        return src.iloc[0:0].copy()

    grouped = src.set_index("time")
    rule = "10min"
    agg = grouped.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    counts = grouped["close"].resample(rule, label="left", closed="left").count()
    # Keep complete 2-bar buckets only so a partial last 10m is not a feature.
    complete = counts >= 2
    agg = agg.loc[complete].dropna(subset=["open", "high", "low", "close"])
    out = agg.reset_index()
    out = out.rename(columns={"time": "time"})
    out["timestamp"] = out["time"]
    return out.sort_values("time").reset_index(drop=True)


def closed_bars_asof(
    tf_df: pd.DataFrame,
    decision_time: pd.Timestamp,
    *,
    resolution_minutes: int,
) -> pd.DataFrame:
    """Rows of ``tf_df`` whose candle close time is ``<= decision_time``.

    A 1h bar that opened at 10:00 is still forming at 10:17 and is excluded.
    """
    frame = _ensure_time_column(tf_df)
    if frame.empty:
        return frame
    close_t = bar_close_time(frame["time"], resolution_minutes)
    t = pd.Timestamp(decision_time)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return frame.loc[close_t <= t].reset_index(drop=True)


def asof_join_last_closed(
    decision_times: Sequence[pd.Timestamp],
    tf_df: pd.DataFrame,
    *,
    resolution_minutes: int,
) -> pd.DataFrame:
    """For each decision time, attach the last fully closed TF bar (as-of)."""
    left = pd.DataFrame(
        {"decision_time": pd.to_datetime(list(decision_times), utc=True)}
    ).sort_values("decision_time")
    right = _ensure_time_column(tf_df)
    if right.empty:
        empty = left.copy()
        empty["time"] = pd.NaT
        return empty
    right = right.copy()
    right["close_time"] = bar_close_time(right["time"], resolution_minutes)
    right = right.sort_values("close_time")
    merged = pd.merge_asof(
        left,
        right,
        left_on="decision_time",
        right_on="close_time",
        direction="backward",
        allow_exact_matches=True,
    )
    # Guard: never keep a bar that closed after the decision clock.
    late = merged["close_time"].notna() & (merged["close_time"] > merged["decision_time"])
    if late.any():
        merged.loc[late, right.columns] = np.nan
    return merged


def last_n_closed_bars(
    tf_df: pd.DataFrame,
    decision_time: pd.Timestamp,
    *,
    resolution_minutes: int,
    window_len: int,
) -> pd.DataFrame:
    """Last ``window_len`` fully closed native bars at ``decision_time``."""
    closed = closed_bars_asof(
        tf_df, decision_time, resolution_minutes=resolution_minutes
    )
    if len(closed) < int(window_len):
        return closed
    return closed.iloc[-int(window_len) :].reset_index(drop=True)


def normalize_mtf_frames(
    frames: Mapping[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """Ensure every fusion TF frame has UTC ``time`` (build 10m if missing)."""
    out: Dict[str, pd.DataFrame] = {}
    for res, df in frames.items():
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            continue
        out[str(res)] = _ensure_time_column(df)
    if "10m" not in out and "5m" in out:
        out["10m"] = build_10m_ohlcv_from_5m(out["5m"])
    return out


def fusion_frames_from_fetch(
    df5m: pd.DataFrame,
    df30m: pd.DataFrame,
    df1h: pd.DataFrame,
    df2h: pd.DataFrame,
    *,
    df10m: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Assemble the five independent OHLCV datasets used by the fused model."""
    frames: Dict[str, pd.DataFrame] = {
        "5m": df5m,
        "30m": df30m,
        "1h": df1h,
        "2h": df2h,
    }
    if df10m is not None and not df10m.empty:
        frames["10m"] = df10m
    return normalize_mtf_frames(frames)


def assert_no_lookahead(
    tf_df: pd.DataFrame,
    decision_time: pd.Timestamp,
    *,
    resolution_minutes: int,
) -> None:
    """Raise if any bar close time is after the decision clock."""
    closed = closed_bars_asof(
        tf_df, decision_time, resolution_minutes=resolution_minutes
    )
    if closed.empty:
        return
    close_t = bar_close_time(closed["time"], resolution_minutes)
    t = pd.Timestamp(decision_time)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    if bool((close_t > t).any()):
        raise AssertionError(
            f"Lookahead: {resolution_minutes}m bar close after {t.isoformat()}"
        )


def resolution_minutes(resolution: str) -> int:
    res = str(resolution).strip().lower()
    if res not in RESOLUTION_MINUTES:
        raise ValueError(f"Unsupported resolution {resolution!r}")
    return int(RESOLUTION_MINUTES[res])


def required_fusion_resolutions() -> Sequence[str]:
    return FUSION_INPUT_RESOLUTIONS


def frames_have_fusion_inputs(frames: Mapping[str, Any]) -> bool:
    """True when every fusion TF is present and non-empty."""
    for res in FUSION_INPUT_RESOLUTIONS:
        df = frames.get(res)
        if not isinstance(df, pd.DataFrame) or df.empty:
            return False
    return True
