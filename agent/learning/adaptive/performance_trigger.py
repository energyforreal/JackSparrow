"""Performance-based retrain trigger from recent trade_outcomes (agent DB)."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agent.core.config import settings

logger = structlog.get_logger()


def _sync_database_url(url: str) -> str:
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _fetch_recent_pnls(database_url: str, limit: int) -> List[float]:
    engine = create_engine(_sync_database_url(database_url), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT pnl
                    FROM trade_outcomes
                    ORDER BY closed_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
            return [_safe_float(row[0], 0.0) for row in result]
    finally:
        engine.dispose()


@dataclass
class PerformanceSnapshot:
    sample_size: int
    win_rate: float
    profit_factor: float
    max_drawdown_frac: float


def _max_drawdown_from_pnls(pnls: List[float]) -> float:
    """Max drawdown (fraction of peak equity) from PnL series in chronological order (oldest first)."""
    if not pnls:
        return 0.0
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    return float(max_dd)


def evaluate_recent_performance(database_url: Optional[str]) -> Optional[PerformanceSnapshot]:
    """Return metrics over the configured rolling window, or None if unavailable."""
    if not database_url:
        return None
    window = int(settings.adaptive_performance_rolling_trades)
    window = max(10, window)
    try:
        pnls_recent_first = _fetch_recent_pnls(database_url, window)
    except Exception as e:
        logger.warning(
            "adaptive_performance_fetch_failed",
            service="agent",
            component="performance_trigger",
            error=str(e),
            exc_info=True,
        )
        return None

    if len(pnls_recent_first) < int(settings.adaptive_performance_min_trades):
        return None

    wins = sum(1 for v in pnls_recent_first if v > 0)
    win_rate = wins / max(len(pnls_recent_first), 1)
    gross_profit = sum(v for v in pnls_recent_first if v > 0)
    gross_loss = abs(sum(v for v in pnls_recent_first if v < 0))
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 1.0)
    )
    # oldest-first for drawdown
    # SQL returns newest-first; equity path needs oldest-first
    dd = _max_drawdown_from_pnls(list(reversed(pnls_recent_first)))
    return PerformanceSnapshot(
        sample_size=len(pnls_recent_first),
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_frac=dd,
    )


def should_retrain_from_performance(snapshot: PerformanceSnapshot) -> Tuple[bool, Dict[str, Any]]:
    """True when win rate or profit factor is below floors or drawdown above ceiling."""
    wr_floor = float(settings.adaptive_performance_win_rate_floor)
    pf_floor = float(settings.adaptive_performance_profit_factor_floor)
    dd_ceiling = float(settings.adaptive_performance_max_drawdown_ceiling)

    reasons = []
    if snapshot.win_rate < wr_floor:
        reasons.append("win_rate")
    if snapshot.profit_factor < pf_floor:
        reasons.append("profit_factor")
    if snapshot.max_drawdown_frac > dd_ceiling:
        reasons.append("max_drawdown")

    detail = {
        "win_rate": snapshot.win_rate,
        "profit_factor": snapshot.profit_factor,
        "max_drawdown_frac": snapshot.max_drawdown_frac,
        "sample_size": snapshot.sample_size,
        "floors": {"win_rate": wr_floor, "profit_factor": pf_floor},
        "dd_ceiling": dd_ceiling,
        "reasons": reasons,
    }
    return bool(reasons), detail


def performance_retrain_triggered() -> Tuple[bool, Dict[str, Any]]:
    """Entry point for adaptive_controller (sync)."""
    if not bool(settings.adaptive_performance_retrain_enabled):
        return False, {"disabled": True}
    db_url = os.environ.get("DATABASE_URL") or str(settings.database_url)
    snap = evaluate_recent_performance(db_url or None)
    if snap is None:
        return False, {"reason": "no_snapshot"}
    should, detail = should_retrain_from_performance(snap)
    return should, detail
