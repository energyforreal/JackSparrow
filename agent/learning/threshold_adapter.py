"""
Bounded adaptive thresholds from recent trade_outcomes (Phase 2 learning).

Nudges Redis keys consumed by dynamic_thresholds / reasoning / trading handler.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agent.core.config import settings
from agent.learning.dynamic_thresholds import (
    REDIS_KEY_MILD,
    REDIS_KEY_STRONG,
    REDIS_KEY_MIN_CONF,
    MILD_BOUNDS,
    STRONG_BOUNDS,
    MIN_CONF_BOUNDS,
    _clamp,
)

logger = structlog.get_logger()


def _sync_database_url(url: str) -> str:
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


class ThresholdAdapter:
    """Read trade_outcomes and nudge mild_thresh / min_confidence in Redis."""

    WINDOW = 50
    MIN_ROWS = 20

    async def adapt(self) -> Optional[Dict[str, Any]]:
        """Run one adaptation cycle. Returns summary dict or None if skipped."""
        if not getattr(settings, "threshold_adapter_enabled", True):
            return None

        db_url = getattr(settings, "database_url", None)
        if not db_url:
            return None

        try:
            from agent.core.redis_config import get_redis

            redis_client = await get_redis()
            if not redis_client:
                return None

            rows = await self._fetch_recent_outcomes(db_url, self.WINDOW)
            if len(rows) < self.MIN_ROWS:
                logger.debug(
                    "threshold_adapter_skipped_insufficient_data",
                    row_count=len(rows),
                    min_rows=self.MIN_ROWS,
                )
                return None

            # trade_outcomes rows are closed positions only (not HOLD signals).
            wins = sum(1 for r in rows if float(r.get("pnl") or 0) > 0)
            win_rate = wins / max(len(rows), 1)
            pnl_values = [float(r.get("pnl") or 0) for r in rows]
            pnl_mean = sum(pnl_values) / max(len(rows), 1)
            gross_profit = sum(v for v in pnl_values if v > 0)
            gross_loss = abs(sum(v for v in pnl_values if v < 0))
            profit_factor = (
                gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 1.0)
            )

            cur_mild_s = await redis_client.get(REDIS_KEY_MILD)
            cur_mild = float(cur_mild_s) if cur_mild_s is not None else 0.18
            cur_strong_s = await redis_client.get(REDIS_KEY_STRONG)
            cur_strong = float(cur_strong_s) if cur_strong_s is not None else 0.40
            cur_conf_s = await redis_client.get(REDIS_KEY_MIN_CONF)
            cur_conf = (
                float(cur_conf_s)
                if cur_conf_s is not None
                else float(getattr(settings, "min_confidence_threshold", 0.52) or 0.52)
            )

            # If outcomes are statistically flat, avoid nudging thresholds.
            if 0.45 <= win_rate <= 0.55 and abs(pnl_mean) < 1e-8:
                logger.debug(
                    "threshold_adapter_skipped_flat_outcomes",
                    sample_size=len(rows),
                    win_rate=win_rate,
                    pnl_mean=pnl_mean,
                    profit_factor=profit_factor,
                )
                return None

            new_mild = cur_mild
            new_strong = cur_strong
            if win_rate < 0.40 or profit_factor < 0.90:
                new_mild = min(MILD_BOUNDS[1], cur_mild + 0.01)
                new_strong = min(STRONG_BOUNDS[1], cur_strong + 0.01)
            elif win_rate > 0.55 and pnl_mean > 0 and profit_factor > 1.10:
                new_mild = max(MILD_BOUNDS[0], cur_mild - 0.01)
                new_strong = max(STRONG_BOUNDS[0], cur_strong - 0.01)

            new_conf = cur_conf
            if win_rate < 0.40 or profit_factor < 0.90:
                new_conf = min(MIN_CONF_BOUNDS[1], cur_conf + 0.01)
            elif win_rate > 0.55 and pnl_mean > 0 and profit_factor > 1.10:
                new_conf = max(MIN_CONF_BOUNDS[0], cur_conf - 0.01)

            new_mild = _clamp(new_mild, MILD_BOUNDS[0], MILD_BOUNDS[1])
            new_strong = _clamp(new_strong, STRONG_BOUNDS[0], STRONG_BOUNDS[1])
            new_conf = _clamp(new_conf, MIN_CONF_BOUNDS[0], MIN_CONF_BOUNDS[1])
            if new_strong < new_mild + 0.05:
                new_strong = _clamp(new_mild + 0.05, STRONG_BOUNDS[0], STRONG_BOUNDS[1])

            await redis_client.set(REDIS_KEY_MILD, f"{new_mild:.4f}")
            await redis_client.set(REDIS_KEY_STRONG, f"{new_strong:.4f}")
            await redis_client.set(REDIS_KEY_MIN_CONF, f"{new_conf:.4f}")
            await redis_client.set(
                "learning:thresholds_updated_at",
                datetime.now(timezone.utc).isoformat(),
            )

            summary = {
                "win_rate": win_rate,
                "pnl_mean": pnl_mean,
                "profit_factor": profit_factor,
                "old_mild_thresh": cur_mild,
                "new_mild_thresh": new_mild,
                "old_strong_thresh": cur_strong,
                "new_strong_thresh": new_strong,
                "old_min_confidence": cur_conf,
                "new_min_confidence": new_conf,
                "sample_size": len(rows),
            }
            logger.info("threshold_adapter_applied", **summary)
            return summary
        except Exception as e:
            logger.warning("threshold_adapter_failed", error=str(e), exc_info=True)
            return None

    async def _fetch_recent_outcomes(self, database_url: str, limit: int) -> List[Dict[str, Any]]:
        """Load recent trade rows (sync DB in thread)."""
        import asyncio

        def _sync_fetch() -> List[Dict[str, Any]]:
            engine = create_engine(_sync_database_url(database_url), poolclass=NullPool)
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT signal, pnl, closed_at
                        FROM trade_outcomes
                        ORDER BY closed_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
                return [dict(row._mapping) for row in result]

        return await asyncio.to_thread(_sync_fetch)
