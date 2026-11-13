"""Annotation schema and future breakout targets.

Neither table is copied into the sequence tensor. A blank annotation does
not inherit the candidate's proposed class.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from research.cpr_mtf.candidates import Candidate
from research.cpr_mtf.contract import (
    ANNOTATION_FIELDS,
    BREAKOUT_BUFFER_ATR,
    BREAKOUT_HORIZONS,
    BREAKOUT_STATUSES,
    BREAKOUT_STRONG_ATR,
    DIRECTIONS,
    MATURITY_STATES,
    PATTERN_CLASSES,
)

_IDENTITY = frozenset(("", "reject", *PATTERN_CLASSES))
_DIRECTION = frozenset(("", *DIRECTIONS))
_MATURITY = frozenset(("", *MATURITY_STATES))


def blank_annotation(candidate_id: str) -> dict[str, object]:
    """Return an empty review row for ``candidate_id``.

    Args:
        candidate_id: Stable proposal id. The identity field stays empty.

    Returns:
        Annotation record with no class, direction, or maturity.
    """
    return {
        "candidate_id": candidate_id,
        "identity": "",
        "direction": "",
        "maturity": "",
        "upper_boundary_atr": None,
        "lower_boundary_atr": None,
        "start_frac": None,
        "end_frac": None,
        "annotator": "",
        "notes": "",
    }


def validate_annotation(row: Mapping[str, object]) -> None:
    """Reject an annotation row that uses unknown fields or label values.

    Args:
        row: One JSON object.

    Raises:
        ValueError: If a field, identity, direction, or maturity is unknown,
            or the candidate id is empty.
    """
    extra = set(row) - set(ANNOTATION_FIELDS)
    if extra:
        raise ValueError(f"annotation has unknown fields: {sorted(extra)}")
    missing = set(ANNOTATION_FIELDS) - set(row)
    if missing:
        raise ValueError(f"annotation is missing fields: {sorted(missing)}")
    if not str(row["candidate_id"]).strip():
        raise ValueError("annotation candidate_id is empty")
    if row["identity"] not in _IDENTITY:
        raise ValueError(f"annotation identity is not allowed: {row['identity']}")
    if row["direction"] not in _DIRECTION:
        raise ValueError(f"annotation direction is not allowed: {row['direction']}")
    if row["maturity"] not in _MATURITY:
        raise ValueError(f"annotation maturity is not allowed: {row['maturity']}")


def write_annotations(path: Path, rows: list[Mapping[str, object]]) -> None:
    """Write validated annotation rows as JSONL.

    Args:
        path: Destination file. Parent directories are created.
        rows: Annotation records. An empty list writes an empty file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            validate_annotation(row)
            handle.write(json.dumps(dict(row)) + "\n")


def read_annotations(path: Path) -> list[dict[str, object]]:
    """Read annotation JSONL.

    Args:
        path: File written by ``write_annotations``. A missing file is empty.

    Returns:
        Validated rows in file order.
    """
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        validate_annotation(row)
        rows.append(row)
    return rows


def breakout_rows(
    frame: pd.DataFrame,
    candidate: Candidate,
    asof_index: int,
) -> list[dict[str, object]]:
    """Build the 12-bar and 24-bar breakout targets for one proposal.

    Args:
        frame: Native-timeframe OHLCV. Rows after ``asof_index`` are labels.
        candidate: Proposal whose boundaries are fixed at ``asof_index``.
        asof_index: Last bar that may inform the boundaries.

    Returns:
        One row per horizon. Status is never written onto a feature frame.
    """
    return [
        {
            "candidate_id": candidate.candidate_id,
            "horizon_bars": horizon,
            "status": breakout_status(frame, candidate, asof_index, horizon),
        }
        for horizon in BREAKOUT_HORIZONS
    ]


def breakout_status(
    frame: pd.DataFrame,
    candidate: Candidate,
    asof_index: int,
    horizon: int,
) -> str:
    """Classify the future path of one proposal over ``horizon`` native bars.

    Args:
        frame: Native OHLCV.
        candidate: Proposal boundaries at the as-of bar.
        asof_index: Last input bar.
        horizon: Number of completed bars after ``asof_index``.

    Returns:
        One of ``BREAKOUT_STATUSES``.
    """
    if asof_index + horizon >= len(frame):
        return "masked"
    atr = candidate.atr if candidate.atr > 0.0 else 1e-9
    buffer = BREAKOUT_BUFFER_ATR * atr
    strong = BREAKOUT_STRONG_ATR * atr
    run_up = 0
    run_down = 0
    for step in range(1, horizon + 1):
        index = asof_index + step
        upper = candidate.upper_price_at_asof + candidate.upper_slope * step
        lower = candidate.lower_price_at_asof + candidate.lower_slope * step
        high = float(frame["high"].iloc[index])
        low = float(frame["low"].iloc[index])
        close = float(frame["close"].iloc[index])
        close_up = close > upper + buffer
        close_down = close < lower - buffer
        if (high >= upper + buffer and low <= lower - buffer) or (close_up and close_down):
            return "ambiguous"
        if close > upper + strong:
            return _status_name("up", candidate.direction)
        if close < lower - strong:
            return _status_name("down", candidate.direction)
        if close_up:
            run_up += 1
            run_down = 0
        elif close_down:
            run_down += 1
            run_up = 0
        else:
            run_up = 0
            run_down = 0
        if run_up >= 2:
            return _status_name("up", candidate.direction)
        if run_down >= 2:
            return _status_name("down", candidate.direction)
    return "no_breakout"


def _status_name(side: str, direction: str) -> str:
    """Map a confirmed side to a breakout or invalidation status."""
    if side not in {"up", "down"}:
        raise ValueError(f"unknown breakout side: {side}")
    if direction == "bullish":
        return "upside_breakout" if side == "up" else "invalidated"
    if direction == "bearish":
        return "downside_breakout" if side == "down" else "invalidated"
    if direction not in {"neutral", ""}:
        raise ValueError(f"unknown proposal direction: {direction}")
    status = "upside_breakout" if side == "up" else "downside_breakout"
    if status not in BREAKOUT_STATUSES:
        raise ValueError(status)
    return status
