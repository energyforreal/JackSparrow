"""
Bounded adaptive thresholds from recent trade_outcomes (Phase 2 learning).

Nudges Redis keys consumed by dynamic_thresholds / reasoning / trading handler.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
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
_ADAPT_LOCK = asyncio.Lock()


def _sync_database_url(url: str) -> str:
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _extract_regime_from_row(row: Dict[str, Any]) -> str:
    """Read regime from trade_outcomes.metadata when present."""
    meta = row.get("metadata")
    if not isinstance(meta, dict):
        return "unknown"
    dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    ms = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    return str(ms.get("regime") or "unknown")


def _segment_rows_by_regime(
    rows: List[Dict[str, Any]],
    *,
    min_rows: int,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Keep rows for the dominant regime when the segment has enough samples."""
    if not rows:
        return rows, None
    counts: Dict[str, int] = {}
    for row in rows:
        regime = _extract_regime_from_row(row)
        counts[regime] = counts.get(regime, 0) + 1
    dominant = max(counts, key=counts.get)
    segmented = [r for r in rows if _extract_regime_from_row(r) == dominant]
    if len(segmented) >= min_rows:
        return segmented, dominant
    return rows, dominant


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


class ThresholdAdapter:
    """Read trade_outcomes and nudge mild_thresh / min_confidence in Redis."""

    WINDOW = 50
    MIN_ROWS = 20
    _recent_directions: List[int] = []

    async def adapt(self) -> Optional[Dict[str, Any]]:
        """Run one adaptation cycle. Returns summary dict or None if skipped."""
        if not getattr(settings, "threshold_adapter_enabled", True):
            return None
        if _ADAPT_LOCK.locked():
            logger.debug("threshold_adapter_skipped_in_progress")
            return None

        db_url = getattr(settings, "database_url", None)
        if not db_url:
            return None

        try:
            async with _ADAPT_LOCK:
                from agent.core.redis_config import get_redis

                redis_client = await get_redis()
                if not redis_client:
                    return None

                rows = await self._fetch_recent_outcomes(db_url, self.WINDOW)
                regime_aware = bool(
                    getattr(settings, "threshold_adapter_regime_aware", False)
                )
                segment_regime: Optional[str] = None
                if regime_aware and rows:
                    rows, segment_regime = _segment_rows_by_regime(
                        rows,
                        min_rows=self.MIN_ROWS,
                    )

                if len(rows) < self.MIN_ROWS:
                    logger.debug(
                        "threshold_adapter_skipped_insufficient_data",
                        row_count=len(rows),
                        min_rows=self.MIN_ROWS,
                    )
                    return None

                # trade_outcomes rows are closed positions only (not HOLD signals).
                pnl_values = [_safe_float(r.get("pnl"), 0.0) for r in rows]
                wins = sum(1 for v in pnl_values if v > 0)
                win_rate = wins / max(len(rows), 1)
                pnl_mean = sum(pnl_values) / max(len(rows), 1)
                gross_profit = sum(v for v in pnl_values if v > 0)
                gross_loss = abs(sum(v for v in pnl_values if v < 0))
                profit_factor = (
                    gross_profit / gross_loss
                    if gross_loss > 0
                    else (999.0 if gross_profit > 0 else 1.0)
                )

                cur_mild_s = await redis_client.get(REDIS_KEY_MILD)
                cur_mild = _safe_float(cur_mild_s, 0.18)
                cur_strong_s = await redis_client.get(REDIS_KEY_STRONG)
                cur_strong = _safe_float(cur_strong_s, 0.40)
                cur_conf_s = await redis_client.get(REDIS_KEY_MIN_CONF)
                cur_conf = _safe_float(
                    cur_conf_s,
                    float(getattr(settings, "min_confidence_threshold", 0.52) or 0.52),
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

                direction = 0
                new_mild = cur_mild
                new_strong = cur_strong
                if win_rate < 0.40 or profit_factor < 0.90:
                    direction = 1
                    new_mild = min(MILD_BOUNDS[1], cur_mild + 0.01)
                    new_strong = min(STRONG_BOUNDS[1], cur_strong + 0.01)
                elif win_rate > 0.55 and pnl_mean > 0 and profit_factor > 1.10:
                    direction = -1
                    new_mild = max(MILD_BOUNDS[0], cur_mild - 0.01)
                    new_strong = max(STRONG_BOUNDS[0], cur_strong - 0.01)

                new_conf = cur_conf
                if win_rate < 0.40 or profit_factor < 0.90:
                    new_conf = min(MIN_CONF_BOUNDS[1], cur_conf + 0.01)
                elif win_rate > 0.55 and pnl_mean > 0 and profit_factor > 1.10:
                    new_conf = max(MIN_CONF_BOUNDS[0], cur_conf - 0.01)

                if direction != 0:
                    recent = ThresholdAdapter._recent_directions
                    if (
                        len(recent) >= 2
                        and recent[-1] == -direction
                        and recent[-2] == -direction
                        and recent[-1] != direction
                    ):
                        logger.debug(
                            "threshold_adapter_skipped_oscillation",
                            direction=direction,
                            recent=recent[-2:],
                        )
                        return None
                    recent.append(direction)
                    ThresholdAdapter._recent_directions = recent[-6:]

                new_mild = _clamp(new_mild, MILD_BOUNDS[0], MILD_BOUNDS[1])
                new_strong = _clamp(new_strong, STRONG_BOUNDS[0], STRONG_BOUNDS[1])
                new_conf = _clamp(new_conf, MIN_CONF_BOUNDS[0], MIN_CONF_BOUNDS[1])
                if new_strong < new_mild + 0.05:
                    new_strong = _clamp(new_mild + 0.05, STRONG_BOUNDS[0], STRONG_BOUNDS[1])

                # Keep threshold updates consistent in one Redis transaction.
                pipe = redis_client.pipeline(transaction=True)
                pipe.set(REDIS_KEY_MILD, f"{new_mild:.4f}")
                pipe.set(REDIS_KEY_STRONG, f"{new_strong:.4f}")
                pipe.set(REDIS_KEY_MIN_CONF, f"{new_conf:.4f}")
                pipe.set("learning:thresholds_updated_at", datetime.now(timezone.utc).isoformat())
                await pipe.execute()

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
                    "regime_segment": segment_regime,
                    "regime_aware": regime_aware,
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
            try:
                with engine.connect() as conn:
                    result = conn.execute(
                        text(
                            """
                            SELECT signal, pnl, closed_at, metadata
                            FROM trade_outcomes
                            ORDER BY closed_at DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                    out: List[Dict[str, Any]] = []
                    for row in result:
                        mapped = dict(row._mapping)
                        meta = mapped.get("metadata")
                        if isinstance(meta, str):
                            try:
                                import json

                                mapped["metadata"] = json.loads(meta)
                            except (TypeError, ValueError):
                                mapped["metadata"] = {}
                        out.append(mapped)
                    return out
            finally:
                engine.dispose()

        return await asyncio.to_thread(_sync_fetch)
