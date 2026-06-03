"""Parse decision payload timestamps for age checks (UTC-naive safe on Windows)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def parse_utc_datetime(ts: Any) -> Optional[datetime]:
    """Parse a value to timezone-aware UTC datetime (naive inputs treated as UTC)."""
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            v = float(ts)
            if v > 1e12:
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        if isinstance(ts, str):
            s = ts.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return None


def decision_payload_timestamp_epoch_seconds(ts: Any) -> Optional[float]:
    """Convert decision payload `timestamp` to Unix seconds for age checks.

    Naive datetimes are treated as UTC. The pipeline uses `datetime.now(timezone.utc)` for
    decision times; on Windows, `datetime.timestamp()` treats naive values as
    *local* time, which skews age by the host timezone offset (~19800s on IST).
    """
    dt = parse_utc_datetime(ts)
    if dt is None:
        return None
    try:
        return dt.timestamp()
    except (TypeError, ValueError, OSError):
        return None


def decision_payload_age_seconds(payload: Dict[str, Any]) -> Optional[float]:
    """Age of a decision payload in seconds for stale-signal checks.

    Prefers ``server_timestamp_ms`` (set at DecisionReady emit) over ``timestamp``,
    which may be a bar time or a naive datetime after Redis JSON round-trip.
    """
    if not isinstance(payload, dict):
        return None
    server_ms = payload.get("server_timestamp_ms")
    if server_ms is not None:
        try:
            ms = float(server_ms)
            if ms > 0:
                return max(0.0, time.time() - ms / 1000.0)
        except (TypeError, ValueError):
            pass
    ts_sec = decision_payload_timestamp_epoch_seconds(payload.get("timestamp"))
    if ts_sec is None:
        return None
    return max(0.0, time.time() - ts_sec)
