"""Timestamp, gap, and OHLC audit for the 30-minute BTCUSD research set.

The audit reports defects. It does not fill missing bars or drop them silently.
A signal is horizon-eligible only when all 24 future 30-minute timestamps exist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from agent.data.candle_validation import resolution_to_seconds

SPEC_VERSION = "forecast-30m-h24-phase1"
INSTRUMENT = "BTCUSD"
RESOLUTION = "30m"
HORIZON_BARS = 24
HOLDOUT_FRACTION = 0.15
MIN_SOURCE_ROWS = 20_000
EXAMPLE_LIMIT = 20
OHLCV_COLUMNS = ("time", "open", "high", "low", "close", "volume")
EXCLUDED_FROM_FEATURES = ("funding_rate", "open_interest")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def bar_seconds(resolution: str = RESOLUTION) -> int:
    """Return the bar length in seconds for a candle resolution."""
    return resolution_to_seconds(resolution)


def to_epoch_seconds(timestamps: pd.Series) -> np.ndarray:
    """Convert timestamps to UTC Unix seconds.

    Args:
        timestamps: Datetime-like values. Naive values are treated as UTC.

    Returns:
        int64 Unix seconds, one per input row.
    """
    converted = pd.to_datetime(timestamps, utc=True)
    nanoseconds = converted.dt.as_unit("ns").astype("int64")
    return (nanoseconds // 1_000_000_000).to_numpy(dtype=np.int64)


def file_sha256(path: Path) -> str:
    """Hash a file in streaming chunks.

    Args:
        path: File to hash.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    """Return a repo-relative POSIX path when the file lives in the repo."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def horizon_eligibility(
    epoch_s: np.ndarray,
    *,
    bar_length: int,
    horizon_bars: int = HORIZON_BARS,
) -> dict[str, int]:
    """Count signals whose next ``horizon_bars`` timestamps all exist.

    Args:
        epoch_s: Unique, ascending Unix seconds.
        bar_length: Expected spacing in seconds.
        horizon_bars: Number of future bars required.

    Returns:
        Eligible rows, tail rows whose horizon runs past the sample, and
        interior rows whose horizon crosses a missing timestamp.

    Raises:
        ValueError: If the horizon is not positive.
    """
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be positive")
    times = np.asarray(epoch_s, dtype=np.int64)
    present = set(int(value) for value in times.tolist())
    last = int(times[-1]) if len(times) else 0
    horizon_span = int(horizon_bars) * int(bar_length)
    eligible = 0
    tail_ineligible = 0
    gap_ineligible = 0
    for raw in times.tolist():
        start = int(raw)
        if start + horizon_span > last:
            tail_ineligible += 1
            continue
        if all(
            (start + step * bar_length) in present
            for step in range(1, horizon_bars + 1)
        ):
            eligible += 1
        else:
            gap_ineligible += 1
    return {
        "eligible_rows": eligible,
        "tail_ineligible_rows": tail_ineligible,
        "gap_ineligible_rows": gap_ineligible,
    }


def chronological_split(
    epoch_s: np.ndarray,
    *,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> dict[str, Any]:
    """Cut the last fraction of sorted rows into an unread holdout.

    Args:
        epoch_s: Unique, ascending Unix seconds.
        holdout_fraction: Share of rows reserved at the end. Must be in (0, 0.5).

    Returns:
        Development and holdout bounds. ``development_end_exclusive`` is the
        first holdout timestamp.

    Raises:
        ValueError: If the fraction or the series cannot form both sides.
    """
    if not 0.0 < holdout_fraction < 0.5:
        raise ValueError("holdout_fraction must be between 0 and 0.5")
    times = np.asarray(epoch_s, dtype=np.int64)
    row_count = int(times.shape[0])
    holdout_rows = int(row_count * holdout_fraction)
    if holdout_rows < 1 or holdout_rows >= row_count:
        raise ValueError(
            f"holdout_fraction={holdout_fraction} does not leave both sides "
            f"on {row_count} rows"
        )
    development_rows = row_count - holdout_rows
    cut = int(times[development_rows])
    return {
        "holdout_fraction": float(holdout_fraction),
        "holdout_rule": "last_fraction_of_sorted_rows",
        "development_rows": development_rows,
        "development_start": _iso(int(times[0])),
        "development_end_exclusive": _iso(cut),
        "holdout_rows": holdout_rows,
        "holdout_start": _iso(cut),
        "holdout_end": _iso(int(times[-1])),
        "holdout_status": "unread",
        "purge_bars": HORIZON_BARS,
    }


def source_decision(
    report: Mapping[str, Any],
    *,
    min_rows: int = MIN_SOURCE_ROWS,
) -> dict[str, Any]:
    """Accept a series only when it is long, unique, on-grid, and valid.

    Args:
        report: Frame audit from :func:`audit_frame`.
        min_rows: Minimum deduplicated row count.

    Returns:
        ``accepted`` and the list of blocking reasons. An empty list means the
        file can be the provisional training source.
    """
    reasons: list[str] = []
    if int(report["deduplicated_rows"]) < int(min_rows):
        reasons.append("row_count_below_minimum")
    if int(report["duplicate_extra_rows"]) > 0:
        reasons.append("duplicate_timestamps")
    if int(report["invalid_ohlc_rows"]) > 0:
        reasons.append("invalid_ohlc")
    if int(report["non_finite_timestamps"]) > 0:
        reasons.append("invalid_timestamps")
    if int(report["off_grid_rows"]) > 0:
        reasons.append("off_grid_timestamps")
    if int(report["irregular_intervals"]) > 0:
        reasons.append("irregular_intervals")
    return {"accepted": not reasons, "reasons": reasons, "min_rows": int(min_rows)}


def audit_frame(
    frame: pd.DataFrame,
    *,
    resolution: str = RESOLUTION,
    horizon_bars: int = HORIZON_BARS,
) -> dict[str, Any]:
    """Audit one OHLCV frame without modifying it.

    Args:
        frame: Columns ``time``, ``open``, ``high``, ``low``, ``close``, ``volume``.
        resolution: Candle size. Only ``30m`` is the research baseline.
        horizon_bars: Future bars required for a label.

    Returns:
        Counts, a short list of examples, and horizon eligibility.

    Raises:
        ValueError: If a required column is missing.
    """
    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"OHLCV frame is missing columns: {missing}")

    bar_length = bar_seconds(resolution)
    working = frame.loc[:, list(OHLCV_COLUMNS)].copy()
    timestamps = pd.to_datetime(working["time"], utc=True)
    non_finite_timestamps = int(timestamps.isna().sum())
    input_was_monotonic = bool(timestamps.is_monotonic_increasing) and non_finite_timestamps == 0

    epoch_s = to_epoch_seconds(working["time"])
    finite_mask = timestamps.notna().to_numpy()
    finite_epochs = epoch_s[finite_mask]
    _values, counts = np.unique(finite_epochs, return_counts=True)
    duplicate_values = _values[counts > 1]
    duplicate_extra_rows = int(counts[counts > 1].sum() - duplicate_values.size)

    order = np.argsort(finite_epochs, kind="mergesort")
    sorted_epochs = finite_epochs[order]
    unique_epochs = np.unique(sorted_epochs)
    off_grid_mask = (unique_epochs % bar_length) != 0
    off_grid_rows = int(off_grid_mask.sum())

    intervals = np.diff(unique_epochs) if len(unique_epochs) else np.array([], dtype=np.int64)
    irregular_positions = np.flatnonzero(intervals != bar_length)
    gap_examples = [
        _interval_example(unique_epochs, int(position), bar_length)
        for position in irregular_positions[:EXAMPLE_LIMIT].tolist()
    ]

    prices = working.loc[:, ["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    volume = pd.to_numeric(working["volume"], errors="coerce")
    open_ = prices["open"].to_numpy(dtype=np.float64)
    high = prices["high"].to_numpy(dtype=np.float64)
    low = prices["low"].to_numpy(dtype=np.float64)
    close = prices["close"].to_numpy(dtype=np.float64)
    volume_values = volume.to_numpy(dtype=np.float64)
    invalid_reasons = _invalid_ohlc_masks(open_, high, low, close, volume_values)
    invalid_any = np.zeros(len(working), dtype=bool)
    reason_counts: dict[str, int] = {}
    for reason, mask in invalid_reasons.items():
        reason_counts[reason] = int(mask.sum())
        invalid_any |= mask
    invalid_examples = _invalid_examples(timestamps, invalid_reasons)

    eligibility = (
        horizon_eligibility(unique_epochs, bar_length=bar_length, horizon_bars=horizon_bars)
        if len(unique_epochs)
        else {
            "eligible_rows": 0,
            "tail_ineligible_rows": 0,
            "gap_ineligible_rows": 0,
        }
    )
    deduplicated_rows = int(unique_epochs.size)
    irregular_intervals = int(irregular_positions.size)
    completeness = 1.0
    if deduplicated_rows > 1:
        completeness = 1.0 - (irregular_intervals / (deduplicated_rows - 1))

    excluded = {
        column: _coverage(frame[column])
        for column in EXCLUDED_FROM_FEATURES
        if column in frame.columns
    }
    return {
        "spec_version": SPEC_VERSION,
        "instrument": INSTRUMENT,
        "resolution": resolution,
        "bar_seconds": bar_length,
        "horizon_bars": horizon_bars,
        "horizon_seconds": horizon_bars * bar_length,
        "rows": int(len(working)),
        "deduplicated_rows": deduplicated_rows,
        "input_was_monotonic": input_was_monotonic,
        "non_finite_timestamps": non_finite_timestamps,
        "duplicate_timestamp_values": int(duplicate_values.size),
        "duplicate_extra_rows": duplicate_extra_rows,
        "duplicate_examples": [_iso(int(value)) for value in duplicate_values[:EXAMPLE_LIMIT]],
        "off_grid_rows": off_grid_rows,
        "off_grid_examples": [
            _iso(int(value)) for value in unique_epochs[off_grid_mask][:EXAMPLE_LIMIT]
        ],
        "irregular_intervals": irregular_intervals,
        "gaps": irregular_intervals,
        "completeness": round(float(completeness), 6),
        "gap_examples": gap_examples,
        "invalid_ohlc_rows": int(invalid_any.sum()),
        "invalid_ohlc_reasons": reason_counts,
        "invalid_ohlc_examples": invalid_examples,
        "first_timestamp": _iso(int(unique_epochs[0])) if deduplicated_rows else None,
        "last_timestamp": _iso(int(unique_epochs[-1])) if deduplicated_rows else None,
        "excluded_from_features": excluded,
        **eligibility,
    }


def audit_path(
    path: Path,
    *,
    holdout_fraction: float = HOLDOUT_FRACTION,
    min_rows: int = MIN_SOURCE_ROWS,
) -> dict[str, Any]:
    """Audit a parquet or CSV file and attach the provisional-source decision.

    Args:
        path: OHLCV file.
        holdout_fraction: Last-row fraction reserved for the unread holdout.
        min_rows: Minimum rows required to accept the file.

    Returns:
        Frame audit, file hash, source decision, and chronological split.
        The split is present only when the deduplicated series can be cut.
    """
    frame = _read_table(path)
    report = audit_frame(frame)
    finite = pd.to_datetime(frame["time"], utc=True).notna()
    unique_epochs = np.unique(to_epoch_seconds(frame.loc[finite, "time"]))
    split: dict[str, Any] | None = None
    if len(unique_epochs) > 1:
        split = chronological_split(unique_epochs, holdout_fraction=holdout_fraction)
    decision = source_decision(report, min_rows=min_rows)
    return {
        **report,
        "source_path": repo_relative(path),
        "source_sha256": file_sha256(path),
        "source_decision": decision,
        "split": split,
    }


def render_splits_yaml(report: Mapping[str, Any]) -> str:
    """Render the frozen split calendar.

    Args:
        report: Output of :func:`audit_path`.

    Returns:
        YAML text. The holdout block is marked unread.

    Raises:
        ValueError: If the audit has no split.
    """
    split = report.get("split")
    if not isinstance(split, Mapping):
        raise ValueError("audit report has no chronological split")
    decision = report["source_decision"]
    lines = [
        "# Frozen in Phase 1. Later phases must not move holdout_start.",
        f"spec_version: {report['spec_version']}",
        f"instrument: {report['instrument']}",
        f"resolution: {report['resolution']}",
        "timezone: UTC",
        f"bar_seconds: {report['bar_seconds']}",
        f"horizon_bars: {report['horizon_bars']}",
        f"horizon_seconds: {report['horizon_seconds']}",
        f"holdout_fraction: {split['holdout_fraction']}",
        f"holdout_rule: {split['holdout_rule']}",
        f"purge_bars: {split['purge_bars']}",
        "source:",
        f"  path: {report['source_path']}",
        f"  sha256: {report['source_sha256']}",
        f"  rows: {report['deduplicated_rows']}",
        f"  first_timestamp: {split['development_start']}",
        f"  last_timestamp: {split['holdout_end']}",
        f"  provisional: {str(bool(decision['accepted'])).lower()}",
        "development:",
        f"  start: {split['development_start']}",
        f"  end_exclusive: {split['development_end_exclusive']}",
        f"  rows: {split['development_rows']}",
        "holdout:",
        f"  start: {split['holdout_start']}",
        f"  end: {split['holdout_end']}",
        f"  rows: {split['holdout_rows']}",
        f"  status: {split['holdout_status']}",
        "",
    ]
    return "\n".join(lines)


def write_audit_outputs(
    report: Mapping[str, Any],
    *,
    audit_out: Path,
    splits_out: Path,
) -> None:
    """Write the audit JSON and the split YAML.

    Args:
        report: Output of :func:`audit_path`.
        audit_out: Destination for the JSON report.
        splits_out: Destination for the split calendar.
    """
    audit_out.parent.mkdir(parents=True, exist_ok=True)
    splits_out.parent.mkdir(parents=True, exist_ok=True)
    audit_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    splits_out.write_text(render_splits_yaml(report), encoding="utf-8")


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported OHLCV file type: {path.suffix}")


def _iso(epoch_s: int) -> str:
    return pd.Timestamp(int(epoch_s), unit="s", tz="UTC").isoformat()


def _coverage(series: pd.Series) -> dict[str, float | int]:
    values = pd.to_numeric(series, errors="coerce")
    observed = int(values.notna().sum())
    return {
        "observed": observed,
        "non_null_rate": round(observed / max(len(series), 1), 6),
    }


def _interval_example(
    unique_epochs: np.ndarray,
    position: int,
    bar_length: int,
) -> dict[str, Any]:
    previous = int(unique_epochs[position])
    nxt = int(unique_epochs[position + 1])
    delta = nxt - previous
    missing_bars = max(delta // bar_length - 1, 0)
    return {
        "previous": _iso(previous),
        "next": _iso(nxt),
        "delta_seconds": delta,
        "missing_bars": int(missing_bars),
    }


def _invalid_ohlc_masks(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
) -> dict[str, np.ndarray]:
    finite_price = (
        np.isfinite(open_) & np.isfinite(high) & np.isfinite(low) & np.isfinite(close)
    )
    return {
        "non_finite_price": ~finite_price,
        "high_below_low": finite_price & (high < low),
        "price_outside_bar": finite_price
        & ((close > high) | (close < low) | (open_ > high) | (open_ < low)),
        "non_positive_price": finite_price & ((open_ <= 0.0) | (close <= 0.0)),
        "bad_volume": ~np.isfinite(volume) | (volume < 0.0),
    }


def _invalid_examples(
    timestamps: pd.Series,
    reasons: Mapping[str, np.ndarray],
) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    seen: set[int] = set()
    for reason, mask in reasons.items():
        for position in np.flatnonzero(mask).tolist():
            if position in seen:
                continue
            seen.add(int(position))
            stamp = timestamps.iloc[int(position)]
            text = "NaT" if pd.isna(stamp) else pd.Timestamp(stamp).isoformat()
            examples.append({"timestamp": text, "reason": reason})
            if len(examples) >= EXAMPLE_LIMIT:
                return examples
    return examples


def _cli(argv: Sequence[str] | None = None) -> int:
    import argparse

    import structlog

    parser = argparse.ArgumentParser(description="Audit the 30-minute BTCUSD research series.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=_REPO_ROOT / "export" / "forecast_30m" / "data_audit.json",
    )
    parser.add_argument(
        "--splits-out",
        type=Path,
        default=_REPO_ROOT / "research" / "forecast_30m" / "configs" / "splits.yaml",
    )
    parser.add_argument("--holdout-fraction", type=float, default=HOLDOUT_FRACTION)
    parser.add_argument("--min-rows", type=int, default=MIN_SOURCE_ROWS)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = audit_path(
        args.source,
        holdout_fraction=args.holdout_fraction,
        min_rows=args.min_rows,
    )
    write_audit_outputs(report, audit_out=args.audit_out, splits_out=args.splits_out)
    logger = structlog.get_logger()
    decision = report["source_decision"]
    logger.info(
        "forecast_30m_data_audit",
        source=report["source_path"],
        rows=report["deduplicated_rows"],
        first_timestamp=report["first_timestamp"],
        last_timestamp=report["last_timestamp"],
        gaps=report["gaps"],
        invalid_ohlc_rows=report["invalid_ohlc_rows"],
        eligible_rows=report["eligible_rows"],
        tail_ineligible_rows=report["tail_ineligible_rows"],
        gap_ineligible_rows=report["gap_ineligible_rows"],
        accepted=decision["accepted"],
        reasons=decision["reasons"],
        holdout_start=None if report["split"] is None else report["split"]["holdout_start"],
        audit_out=repo_relative(args.audit_out),
        splits_out=repo_relative(args.splits_out),
    )
    return 0 if decision["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(_cli())
