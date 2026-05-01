"""Strict OHLCV candle validation for training and live data paths.

Enforces exchange-accurate, regularly spaced candles so indicators and models
are not computed on missing or irregular market structure.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Delta-style resolution strings → bar length in seconds
_RESOLUTION_TO_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
    "1w": 604800,
}


def resolution_to_seconds(resolution: str) -> int:
    """Map a resolution string (e.g. ``5m``, ``15m``) to bar length in seconds."""
    key = (resolution or "").strip().lower()
    if key not in _RESOLUTION_TO_SECONDS:
        raise ValueError(f"Unsupported resolution: {resolution!r}")
    return _RESOLUTION_TO_SECONDS[key]


def validate_candles(
    df: pd.DataFrame,
    resolution: str,
    *,
    min_rows: int = 0,
    timestamp_col: str = "timestamp",
    allow_last_irregular: bool = False,
) -> None:
    """Validate candle DataFrame: required columns, monotonic time, regular spacing.

    Args:
        df: DataFrame with at least OHLCV + timestamp.
        resolution: Bar size string (e.g. ``5m``).
        min_rows: Raise if fewer than this many rows (after checks).
        timestamp_col: Name of the timestamp column (datetime-like or ms).
        allow_last_irregular: If True, allow the final bar to have a different
            step (some APIs omit or shorten the forming candle).

    Raises:
        ValueError: On empty frame, missing data, bad spacing, or invalid OHLC.
    """
    if df is None or len(df) == 0:
        raise ValueError("Incomplete candle data: empty DataFrame")

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Incomplete candle data: missing columns {sorted(missing)}")

    if timestamp_col not in df.columns:
        raise ValueError(f"Incomplete candle data: missing {timestamp_col!r}")

    tf_sec = resolution_to_seconds(resolution)
    expected_ms = int(tf_sec * 1000)

    ts = df[timestamp_col]
    if not pd.api.types.is_datetime64_any_dtype(ts.dtype):
        try:
            ts = pd.to_datetime(ts, utc=True)
        except Exception as e:
            raise ValueError(f"Invalid timestamps: {e}") from e

    if ts.isna().any():
        raise ValueError("Invalid candle data: NaT in timestamp column")

    if not ts.is_monotonic_increasing:
        raise ValueError("Invalid candle data: timestamps not strictly increasing")

    if ts.duplicated().any():
        raise ValueError("Invalid candle data: duplicate timestamps")

    # Spacing in milliseconds (numpy datetime64[ns] → int64 ms)
    t64 = ts.values.astype("datetime64[ns]")
    diffs_ms = np.diff(t64.astype(np.int64)) // 1_000_000

    if len(diffs_ms) == 0:
        raise ValueError("Incomplete candle data: single row")

    check = diffs_ms
    if allow_last_irregular and len(diffs_ms) > 1:
        check = diffs_ms[:-1]

    if not np.all(check == expected_ms):
        raise ValueError(
            "Missing or irregular candles detected: "
            f"expected {expected_ms} ms between bars for {resolution!r}"
        )

    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    c = df["close"].astype(float)
    if (h < low).any():
        raise ValueError("Invalid data: high < low in some candles")
    if ((c > h) | (c < low) | (o > h) | (o < low)).any():
        raise ValueError("Invalid data: open/close outside high/low range in some candles")

    if min_rows and len(df) < min_rows:
        raise ValueError(
            f"Incomplete candle data: got {len(df)} rows, require at least {min_rows}"
        )


def dataframe_from_delta_candles(candles: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a DataFrame from ``market_data_service``-formatted candle dicts."""
    if not candles:
        return pd.DataFrame()
    rows_out: list[dict[str, Any]] = []
    for c in candles:
        ts = c.get("timestamp")
        if ts is None:
            raise ValueError("Candle row missing timestamp")
        rows_out.append(
            {
                "timestamp": ts,
                "open": float(c.get("open", 0)),
                "high": float(c.get("high", 0)),
                "low": float(c.get("low", 0)),
                "close": float(c.get("close", 0)),
                "volume": float(c.get("volume", 0)),
            }
        )
    df = pd.DataFrame(rows_out)
    if pd.api.types.is_numeric_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def validate_delta_candle_rows(
    candles: list[dict[str, Any]],
    interval: str,
    *,
    min_rows: int = 1,
    allow_last_irregular: bool = True,
) -> None:
    """Validate REST/WebSocket formatted candles (``timestamp`` in seconds)."""
    df = dataframe_from_delta_candles(candles)
    validate_candles(
        df,
        interval.strip().lower(),
        min_rows=min_rows,
        allow_last_irregular=allow_last_irregular,
    )


def dataframe_from_exchange_rows(
    rows: list[dict[str, Any]],
    *,
    resolution: str,
) -> pd.DataFrame:
    """Normalize raw API candle dicts to a standard DataFrame (no validation)."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.rename(
        columns={
            "time": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
    )
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns and col[0] in df.columns:
            df[col] = df[col[0]]
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df[["open", "high", "low", "close", "volume"]] = df[
        ["open", "high", "low", "close", "volume"]
    ].astype(float)
    return df
