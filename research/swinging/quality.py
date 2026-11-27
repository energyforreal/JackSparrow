"""OHLCV checks, resample comparisons, and dataset manifests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from research.cpr_mtf.bars import resample_ohlcv
from research.swinging.contract import BAR_SECONDS, DELTA_CANDLES_URL, RESOLUTIONS

_OHLC = ("open", "high", "low", "close")


def empty_ohlcv() -> pd.DataFrame:
    """Return an empty OHLCV frame with the canonical columns."""
    return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort, coerce, and dedupe candles on UTC time.

    Args:
        frame: Raw candle rows. ``time`` may be unix seconds or a timestamp.
            ``timestamp`` is accepted as an alias.

    Returns:
        A frame sorted by ``time`` with one row per timestamp.

    Raises:
        ValueError: If a required column is missing.
    """
    if frame is None or frame.empty:
        return empty_ohlcv()
    work = frame.copy()
    if "time" not in work.columns:
        if "timestamp" not in work.columns:
            raise ValueError("candle frame needs a time or timestamp column")
        work["time"] = work["timestamp"]
    missing = [name for name in ("open", "high", "low", "close", "volume") if name not in work.columns]
    if missing:
        raise ValueError(f"candle frame is missing columns: {missing}")
    time = pd.to_datetime(work["time"], utc=True)
    if not pd.api.types.is_datetime64_any_dtype(work["time"]) and pd.api.types.is_numeric_dtype(
        work["time"]
    ):
        time = pd.to_datetime(work["time"], unit="s", utc=True)
    work["time"] = time
    for column in ("open", "high", "low", "close", "volume"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["time", "open", "high", "low", "close"])
    work = work.drop_duplicates(subset="time", keep="last")
    work = work.sort_values("time").reset_index(drop=True)
    return work.loc[:, ["time", "open", "high", "low", "close", "volume"]]


def ohlc_mask(frame: pd.DataFrame) -> pd.Series:
    """Return True for rows whose high and low contain the open and close.

    Args:
        frame: Normalized OHLCV.

    Returns:
        A boolean series aligned to ``frame``.
    """
    if frame.empty:
        return pd.Series(dtype=bool)
    high_ok = frame["high"] >= frame[["open", "close", "low"]].max(axis=1)
    low_ok = frame["low"] <= frame[["open", "close", "high"]].min(axis=1)
    return high_ok & low_ok & frame["high"].ge(frame["low"])


def drop_invalid_ohlc(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove rows that break OHLC consistency.

    Args:
        frame: Normalized OHLCV.

    Returns:
        The valid rows and the number of rows removed.
    """
    if frame.empty:
        return frame.copy(), 0
    mask = ohlc_mask(frame)
    removed = int((~mask).sum())
    return frame.loc[mask].reset_index(drop=True), removed


def gap_report(frame: pd.DataFrame, resolution: str) -> dict[str, Any]:
    """Count missing bars from timestamp spacing.

    Args:
        frame: Normalized OHLCV.
        resolution: Bar size key.

    Returns:
        Rows, gap count, completeness, and the observed span.

    Raises:
        ValueError: If the resolution is unknown.
    """
    if resolution not in BAR_SECONDS:
        raise ValueError(f"unknown resolution: {resolution}")
    if frame.empty:
        return {
            "rows": 0,
            "gaps": 0,
            "completeness": 0.0,
            "earliest": None,
            "latest": None,
        }
    bar_seconds = BAR_SECONDS[resolution]
    stamps = pd.to_datetime(frame["time"], utc=True)
    unit = str(stamps.dtype)
    raw = stamps.astype("int64")
    if unit.startswith("datetime64[us"):
        divisor = 1_000_000
    elif unit.startswith("datetime64[ms"):
        divisor = 1_000
    elif unit.startswith("datetime64[s"):
        divisor = 1
    else:
        divisor = 1_000_000_000
    epochs = (raw // divisor).astype("int64").tolist()
    gaps = 0
    for previous, current in zip(epochs, epochs[1:]):
        if int(current) - int(previous) > bar_seconds * 1.5:
            gaps += 1
    span = max(1, len(epochs) - 1)
    completeness = 1.0 - (gaps / span) if len(epochs) > 1 else 1.0
    return {
        "rows": int(len(epochs)),
        "gaps": int(gaps),
        "completeness": round(float(completeness), 4),
        "earliest": pd.Timestamp(frame["time"].iloc[0]).isoformat(),
        "latest": pd.Timestamp(frame["time"].iloc[-1]).isoformat(),
    }


def compare_native_to_resampled(
    native: pd.DataFrame,
    five_minute: pd.DataFrame,
    resolution: str,
    *,
    price_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Compare native candles with a resample of the 5-minute series.

    Args:
        native: Native timeframe candles.
        five_minute: 5-minute candles covering the same instrument.
        resolution: ``15m``, ``1h``, or ``4h``.
        price_tolerance: Relative close tolerance.

    Returns:
        Overlap counts and the number of closes that disagree.

    Raises:
        ValueError: If ``resolution`` is not a resample target.
    """
    if resolution not in ("15m", "1h", "4h"):
        raise ValueError(f"{resolution} is not resampled from 5-minute bars")
    resampled = resample_ohlcv(five_minute, resolution)
    if native.empty or resampled.empty:
        return {
            "resolution": resolution,
            "native_rows": int(len(native)),
            "resampled_rows": int(len(resampled)),
            "overlap": 0,
            "close_mismatches": 0,
        }
    left = native.copy()
    right = resampled.copy()
    left["time"] = pd.to_datetime(left["time"], utc=True)
    right["time"] = pd.to_datetime(right["time"], utc=True)
    merged = left.merge(right, on="time", suffixes=("_native", "_resampled"))
    if merged.empty:
        mismatches = 0
    else:
        scale = merged["close_native"].abs().clip(lower=1.0)
        delta = (merged["close_native"] - merged["close_resampled"]).abs() / scale
        mismatches = int((delta > price_tolerance).sum())
    return {
        "resolution": resolution,
        "native_rows": int(len(native)),
        "resampled_rows": int(len(resampled)),
        "overlap": int(len(merged)),
        "close_mismatches": mismatches,
    }


def frame_sha256(frame: pd.DataFrame) -> str:
    """Hash the canonical CSV bytes of a frame.

    Args:
        frame: Table to fingerprint.

    Returns:
        Hex sha256.
    """
    payload = frame.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_manifest(
    frame: pd.DataFrame,
    *,
    symbol: str,
    resolution: str,
    kind: str,
    source_error: str | None = None,
) -> dict[str, Any]:
    """Describe one stored series, including the observed timestamp span.

    Args:
        frame: Normalized candles. May be empty when the API returned nothing.
        symbol: Delta symbol that was requested.
        resolution: Candle resolution.
        kind: ``ohlcv``, ``mark``, ``funding``, or ``oi``.
        source_error: Fetch error text when the series is missing.

    Returns:
        JSON-ready manifest. Earliest and latest are null when no rows exist.
    """
    report = gap_report(frame, resolution) if resolution in RESOLUTIONS else {
        "rows": int(len(frame)),
        "gaps": None,
        "completeness": None,
        "earliest": None if frame.empty else pd.Timestamp(frame["time"].iloc[0]).isoformat(),
        "latest": None if frame.empty else pd.Timestamp(frame["time"].iloc[-1]).isoformat(),
    }
    return {
        "symbol": symbol,
        "resolution": resolution,
        "kind": kind,
        "rows": int(len(frame)),
        "earliest": report.get("earliest"),
        "latest": report.get("latest"),
        "gaps": report.get("gaps"),
        "completeness": report.get("completeness"),
        "sha256": frame_sha256(frame),
        "source_url": DELTA_CANDLES_URL,
        "source_error": source_error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON document, creating parent directories.

    Args:
        path: Destination file.
        payload: JSON-ready mapping.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def quality_report(
    frame: pd.DataFrame,
    resolution: str,
    *,
    invalid_rows: int,
    five_minute: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Assemble the data-quality document for one OHLCV series.

    Args:
        frame: Validated OHLCV.
        resolution: Bar size.
        invalid_rows: Rows removed for OHLC inconsistency.
        five_minute: Optional 5-minute frame used to check a native higher timeframe.

    Returns:
        Quality report dictionary.
    """
    report: dict[str, Any] = {
        "resolution": resolution,
        "invalid_ohlc_rows": int(invalid_rows),
        "gaps": gap_report(frame, resolution),
    }
    if five_minute is not None and resolution in ("15m", "1h", "4h"):
        report["resample_check"] = compare_native_to_resampled(frame, five_minute, resolution)
    return report


def decision_data_issues(
    frames: dict[str, pd.DataFrame] | Any,
    *,
    now: datetime | pd.Timestamp | None = None,
    max_stale_bars: int = 2,
) -> list[str]:
    """Reject a decision when the four timeframes are missing, invalid, or stale.

    Args:
        frames: OHLCV keyed by resolution.
        now: Clock used for the closed-candle and staleness checks. A last
            row that is still forming is ignored when an earlier bar exists.
            Historical replays pass ``None`` and only missing or invalid bars
            are rejected.
        max_stale_bars: How many bar lengths a closed candle may lag ``now``.

    Returns:
        Reason codes. An empty list means the frames may be scored.
    """
    issues: list[str] = []
    decision_now = _as_utc(now) if now is not None else None
    source = frames if isinstance(frames, dict) else {}
    for name in RESOLUTIONS:
        frame = source.get(name)
        if frame is None or getattr(frame, "empty", True):
            issues.append(f"missing_{name}")
            continue
        try:
            work = normalize_ohlcv(frame)
        except (TypeError, ValueError, KeyError):
            issues.append(f"invalid_{name}")
            continue
        if work.empty:
            issues.append(f"missing_{name}")
            continue
        if not _values_valid(work):
            issues.append(f"invalid_{name}")
            continue
        if decision_now is None:
            continue
        closed_at, forming = _last_close(work, name, decision_now)
        if name == "5m" and forming:
            issues.append("five_minute_not_closed")
            continue
        if closed_at is None:
            issues.append(f"missing_{name}")
            continue
        limit = pd.Timedelta(seconds=BAR_SECONDS[name] * max(1, int(max_stale_bars)))
        if decision_now - closed_at > limit:
            issues.append(f"stale_{name}")
    return issues


def _as_utc(value: datetime | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _values_valid(frame: pd.DataFrame) -> bool:
    numeric = frame.loc[:, ["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if not bool(numeric.notna().all().all()):
        return False
    if bool((numeric["volume"] < 0).to_numpy().any()):
        return False
    prices = numeric.loc[:, ["open", "high", "low", "close"]]
    if bool((prices <= 0).to_numpy().any()):
        return False
    return bool(ohlc_mask(frame).all())


def _last_close(
    frame: pd.DataFrame,
    resolution: str,
    now: pd.Timestamp,
) -> tuple[pd.Timestamp | None, bool]:
    """Return the last fully closed bar.

    The final row is ignored while it is still forming. ``forming`` is true
    only when the frame has no earlier bar to use.

    Args:
        frame: Normalized OHLCV.
        resolution: Bar size key.
        now: Clock for the close check.

    Returns:
        Close time of the last completed bar, and whether none exists.
    """
    duration = pd.Timedelta(seconds=BAR_SECONDS[resolution])
    opened = pd.Timestamp(frame["time"].iloc[-1])
    if opened.tzinfo is None:
        opened = opened.tz_localize("UTC")
    closed = opened + duration
    if now >= closed:
        return closed, False
    if len(frame) < 2:
        return None, True
    previous = pd.Timestamp(frame["time"].iloc[-2])
    if previous.tzinfo is None:
        previous = previous.tz_localize("UTC")
    return previous + duration, False
