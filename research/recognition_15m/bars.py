"""Resample completed 5-minute BTCUSD candles into 15-minute bars.

A bucket is emitted only when it contains the three clock-aligned 5-minute
bars. The next bucket is never consulted.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from research.recognition_15m.contract import BAR_MINUTES, SOURCE_MINUTES

_OHLCV = ("open", "high", "low", "close", "volume")
_BUCKET = pd.Timedelta(minutes=BAR_MINUTES)
_STEP = pd.Timedelta(minutes=SOURCE_MINUTES)


def _as_utc(values: pd.Series) -> pd.Series:
    """Parse timestamps as UTC.

    Args:
        values: Datetime-like values. Naive values are treated as UTC.

    Returns:
        Timezone-aware UTC timestamps.
    """
    parsed = pd.to_datetime(values, utc=True)
    return pd.Series(parsed, index=values.index)


def dedupe_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the last row for each timestamp.

    Args:
        frame: Candle rows with a ``time`` column.

    Returns:
        Frame sorted by time, with one row per timestamp.
    """
    work = frame.copy()
    work["time"] = _as_utc(work["time"])
    work = work.sort_values("time", kind="mergesort")
    return work.drop_duplicates("time", keep="last").reset_index(drop=True)


def resample_completed_15m(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate contiguous 5-minute bars into completed 15-minute bars.

    Args:
        frame: Columns ``time``, ``open``, ``high``, ``low``, ``close``,
            and ``volume``.

    Returns:
        One row per complete 15-minute bucket, sorted by bucket open time.

    Raises:
        ValueError: If a required column is missing.
    """
    required = {"time", *_OHLCV}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Candle frame is missing columns: {sorted(missing)}")

    work = frame.loc[:, ["time", *_OHLCV]].copy()
    work["time"] = _as_utc(work["time"])
    work = work.sort_values("time", kind="mergesort")
    bucket = work["time"].dt.floor(_BUCKET)
    grouped = work.groupby(bucket, sort=True)
    rows: list[dict[str, object]] = []
    for start, group in grouped:
        if not _bucket_is_complete(group["time"].tolist(), start):
            continue
        ordered = group.sort_values("time", kind="mergesort")
        rows.append(
            {
                "time": pd.Timestamp(start),
                "open": float(ordered["open"].iloc[0]),
                "high": float(ordered["high"].max()),
                "low": float(ordered["low"].min()),
                "close": float(ordered["close"].iloc[-1]),
                "volume": float(ordered["volume"].sum()),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["time", *_OHLCV])
    out = pd.DataFrame(rows)
    out["time"] = pd.to_datetime(out["time"], utc=True)
    return out.reset_index(drop=True)


def _bucket_is_complete(stamps: Iterable[pd.Timestamp], start: pd.Timestamp) -> bool:
    """Return True when the bucket holds exactly the three expected stamps."""
    expected = {
        pd.Timestamp(start),
        pd.Timestamp(start) + _STEP,
        pd.Timestamp(start) + 2 * _STEP,
    }
    seen = [pd.Timestamp(stamp) for stamp in stamps]
    if len(seen) != 3 or len(set(seen)) != 3:
        return False
    return set(seen) == expected


def synthetic_5m(
    buckets: int,
    *,
    start: str = "2024-01-01T00:00:00Z",
    price: float = 100.0,
) -> pd.DataFrame:
    """Build a gap-free 5-minute frame covering ``buckets`` complete groups.

    Args:
        buckets: Number of 15-minute groups.
        start: UTC start, aligned to a 15-minute boundary by the caller.
        price: Flat price level.

    Returns:
        OHLCV frame with three 5-minute rows per bucket.
    """
    count = buckets * 3
    stamps = pd.date_range(start, periods=count, freq="5min", tz="UTC")
    level = np.full(count, price, dtype=np.float64)
    return pd.DataFrame(
        {
            "time": stamps,
            "open": level,
            "high": level + 1.0,
            "low": level - 1.0,
            "close": level + 0.25,
            "volume": np.full(count, 10.0),
        }
    )
