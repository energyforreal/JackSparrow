"""Startup entry grace window for trading handler."""

from __future__ import annotations

import time
from typing import Optional

from agent.core.config import settings

_trading_started_at_mono: Optional[float] = None


def mark_trading_started() -> None:
    """Record agent main-loop start for optional entry grace."""
    global _trading_started_at_mono
    _trading_started_at_mono = time.monotonic()


def reset_trading_started_for_tests() -> None:
    """Clear startup marker (tests only)."""
    global _trading_started_at_mono
    _trading_started_at_mono = None


def startup_grace_blocks_entry() -> bool:
    """True when entries should be blocked during post-start grace period."""
    grace_s = float(getattr(settings, "agent_startup_entry_grace_seconds", 0) or 0)
    if grace_s <= 0 or _trading_started_at_mono is None:
        return False
    elapsed = time.monotonic() - _trading_started_at_mono
    return elapsed < grace_s
