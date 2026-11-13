"""Resample completed 5-minute BTCUSD candles into 15m, 1h, and 4h bars.

A bucket is emitted only when it contains every clock-aligned 5-minute bar.
The next bucket is never consulted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from research.cpr_mtf.contract import (
    BAR_MINUTES,
    SOURCE_BARS_PER_BUCKET,
    SOURCE_MINUTES,
    TIMEFRAMES,
)

_OHLCV = ("open", "high", "low", "close", "volume")
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
        frame: Candle rows with a ``time`` or ``timestamp`` column.

    Returns:
        Frame sorted by time, with one row per timestamp.

    Raises:
        ValueError: If neither time column is present.
    """
    work = _require_ohlcv(frame)
    work["time"] = _as_utc(work["time"])
    work = work.sort_values("time", kind="mergesort")
    return work.drop_duplicates("time", keep="last").reset_index(drop=True)


def load_btcusd_5m(path: Path) -> pd.DataFrame:
    """Load and dedupe a 5-minute BTCUSD parquet file.

    Args:
        path: Parquet path with ``time`` or ``timestamp`` plus OHLCV.

    Returns:
        Deduped frame sorted by UTC time.
    """
    frame = pd.read_parquet(path)
    return dedupe_timestamps(frame)


def resample_ohlcv(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate contiguous 5-minute bars into completed higher-timeframe bars.

    Args:
        frame: Columns ``time``, ``open``, ``high``, ``low``, ``close``,
            and ``volume``.
        timeframe: One of ``15m``, ``1h``, or ``4h``.

    Returns:
        One row per complete bucket, sorted by bucket open time.

    Raises:
        ValueError: If the timeframe or a required column is unknown.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe: {timeframe}")
    work = dedupe_timestamps(frame)
    bucket_delta = pd.Timedelta(minutes=BAR_MINUTES[timeframe])
    expected_count = SOURCE_BARS_PER_BUCKET[timeframe]
    bucket = work["time"].dt.floor(bucket_delta)
    grouped = work.groupby(bucket, sort=True)
    rows: list[dict[str, object]] = []
    for start, group in grouped:
        if not _bucket_is_complete(group["time"].tolist(), start, expected_count):
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


def _require_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the time and OHLCV columns, accepting ``timestamp`` as time."""
    work = frame.copy()
    if "time" not in work.columns:
        if "timestamp" not in work.columns:
            raise ValueError("candle frame needs a time or timestamp column")
        work["time"] = work["timestamp"]
    missing = {"time", *_OHLCV} - set(work.columns)
    if missing:
        raise ValueError(f"candle frame is missing columns: {sorted(missing)}")
    return work.loc[:, ["time", *_OHLCV]].copy()


def _bucket_is_complete(
    stamps: Iterable[pd.Timestamp],
    start: pd.Timestamp,
    expected_count: int,
) -> bool:
    """Return True when the bucket holds exactly the expected source stamps."""
    origin = pd.Timestamp(start)
    expected = {origin + index * _STEP for index in range(expected_count)}
    seen = [pd.Timestamp(stamp) for stamp in stamps]
    if len(seen) != expected_count or len(set(seen)) != expected_count:
        return False
    return set(seen) == expected
