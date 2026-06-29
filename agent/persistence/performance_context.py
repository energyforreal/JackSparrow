"""In-memory rolling performance counters for trade snapshot analytics."""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timezone
from typing import Any, Deque, Dict, Optional

import structlog

logger = structlog.get_logger()

_closed_trades_count: int = 0
_win_streak: int = 0
_loss_streak: int = 0
_recent_outcomes: Deque[bool] = deque(maxlen=50)
_session_realized_pnl_usd: float = 0.0
_daily_realized_pnl_usd: float = 0.0
_daily_pnl_date: Optional[date] = None
_current_drawdown_pct: Optional[float] = None


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _reset_daily_if_needed() -> None:
    global _daily_realized_pnl_usd, _daily_pnl_date
    today = _utc_today()
    if _daily_pnl_date != today:
        _daily_realized_pnl_usd = 0.0
        _daily_pnl_date = today


def snapshot_performance_context() -> Dict[str, Any]:
    """Return point-in-time counters for entry snapshot (no DB read)."""
    _reset_daily_if_needed()
    wins = sum(1 for x in _recent_outcomes if x)
    rolling = wins / len(_recent_outcomes) if _recent_outcomes else None
    out: Dict[str, Any] = {
        "closed_trades_count": _closed_trades_count,
        "win_streak": _win_streak,
        "loss_streak": _loss_streak,
        "session_realized_pnl_usd": round(_session_realized_pnl_usd, 6),
        "daily_realized_pnl_usd": round(_daily_realized_pnl_usd, 6),
    }
    if rolling is not None:
        out["rolling_win_rate_50"] = round(rolling, 4)
    if _current_drawdown_pct is not None:
        out["current_drawdown_pct"] = round(_current_drawdown_pct, 6)
    return out


def record_position_closed(
    *,
    pnl_usd: float,
    drawdown_pct: Optional[float] = None,
) -> None:
    """Update counters after a closed position (in-memory only)."""
    global _closed_trades_count, _win_streak, _loss_streak
    global _session_realized_pnl_usd, _daily_realized_pnl_usd

    _reset_daily_if_needed()
    _closed_trades_count += 1
    _session_realized_pnl_usd += float(pnl_usd or 0)
    _daily_realized_pnl_usd += float(pnl_usd or 0)

    profitable = float(pnl_usd or 0) > 0
    if profitable:
        _win_streak += 1
        _loss_streak = 0
    elif float(pnl_usd or 0) < 0:
        _loss_streak += 1
        _win_streak = 0
    else:
        _win_streak = 0
        _loss_streak = 0

    _recent_outcomes.append(profitable)

    if drawdown_pct is not None:
        global _current_drawdown_pct
        try:
            _current_drawdown_pct = float(drawdown_pct)
        except (TypeError, ValueError):
            pass

    logger.debug(
        "performance_context_updated",
        closed_trades_count=_closed_trades_count,
        win_streak=_win_streak,
        session_pnl_usd=_session_realized_pnl_usd,
    )


def set_drawdown_pct(drawdown_pct: Optional[float]) -> None:
    """Optional hook from risk manager portfolio drawdown."""
    global _current_drawdown_pct
    if drawdown_pct is None:
        return
    try:
        _current_drawdown_pct = float(drawdown_pct)
    except (TypeError, ValueError):
        pass


def reset_for_tests() -> None:
    """Clear counters (unit tests only)."""
    global _closed_trades_count, _win_streak, _loss_streak
    global _session_realized_pnl_usd, _daily_realized_pnl_usd, _daily_pnl_date
    global _current_drawdown_pct
    _closed_trades_count = 0
    _win_streak = 0
    _loss_streak = 0
    _recent_outcomes.clear()
    _session_realized_pnl_usd = 0.0
    _daily_realized_pnl_usd = 0.0
    _daily_pnl_date = None
    _current_drawdown_pct = None
