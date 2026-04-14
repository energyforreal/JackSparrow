"""Parse decision payload timestamps for age checks (UTC-naive safe on Windows)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def decision_payload_timestamp_epoch_seconds(ts: Any) -> Optional[float]:
    """Convert decision payload `timestamp` to Unix seconds for age checks.

    Naive datetimes are treated as UTC. The pipeline uses `datetime.utcnow()` for
    decision times; on Windows, `datetime.timestamp()` treats naive values as
    *local* time, which skews age by the host timezone offset (~19800s on IST).
    """
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            v = float(ts)
            if v > 1e12:
                v /= 1000.0
            return v
        if isinstance(ts, str):
            s = ts.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc).timestamp()
            return ts.timestamp()
        if hasattr(ts, "timestamp"):
            return float(ts.timestamp())
    except (TypeError, ValueError, OSError):
        return None
    return None
