"""Canonical IST and UTC timestamps for paper-trade and signal-audit logs."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist_iso() -> str:
    """Current time in Asia/Kolkata as ISO 8601 (primary audit display)."""
    return datetime.now(IST).isoformat()


def now_utc_iso() -> str:
    """Current time in UTC as ISO 8601 (interoperability / correlation)."""
    return datetime.now(timezone.utc).isoformat()
