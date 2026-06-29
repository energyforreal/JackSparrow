"""Analytics queries over trade_outcomes, entry_decisions, and rollups."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import cast, desc, func, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import (
    AnalyticsRollupRecord,
    EntryDecisionRecord,
    TradeOutcomeRecord,
)

import structlog

logger = structlog.get_logger()


class AnalyticsService:
    """Read-only analytics over persisted trade decision data."""

    async def list_trade_outcomes(
        self,
        db: AsyncSession,
        *,
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        setup_type: Optional[str] = None,
        close_reason: Optional[str] = None,
        config_hash: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = select(TradeOutcomeRecord)
        if symbol:
            query = query.where(TradeOutcomeRecord.symbol == symbol)
        if close_reason:
            query = query.where(TradeOutcomeRecord.close_reason == close_reason)
        if from_date:
            query = query.where(TradeOutcomeRecord.closed_at >= from_date)
        if to_date:
            query = query.where(TradeOutcomeRecord.closed_at <= to_date)
        if regime:
            query = query.where(
                TradeOutcomeRecord.metadata_json["decision_context"]["rule_based_pipeline"][
                    "market_state"
                ]["regime"].astext == regime
            )
        if setup_type:
            query = query.where(
                TradeOutcomeRecord.metadata_json["decision_context"]["rule_based_pipeline"][
                    "structural_gates"
                ]["setup_type"].astext == setup_type
            )
        if config_hash:
            query = query.where(
                TradeOutcomeRecord.metadata_json["system_context"]["config_hash"].astext
                == config_hash
            )
        query = query.order_by(desc(TradeOutcomeRecord.closed_at)).offset(offset).limit(limit)
        result = await db.execute(query)
        rows = result.scalars().all()
        return [self._trade_outcome_row(r) for r in rows]

    async def entry_decision_funnel(
        self,
        db: AsyncSession,
        *,
        symbol: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        query = select(
            EntryDecisionRecord.outcome,
            func.count(EntryDecisionRecord.id).label("count"),
        )
        if symbol:
            query = query.where(EntryDecisionRecord.symbol == symbol)
        if from_date:
            query = query.where(EntryDecisionRecord.timestamp >= from_date)
        if to_date:
            query = query.where(EntryDecisionRecord.timestamp <= to_date)
        query = query.group_by(EntryDecisionRecord.outcome)
        result = await db.execute(query)
        funnel = {str(row.outcome): int(row.count) for row in result.all()}

        reject_query = select(
            EntryDecisionRecord.reject_reason,
            func.count(EntryDecisionRecord.id).label("count"),
        ).where(EntryDecisionRecord.outcome == "rejected")
        if symbol:
            reject_query = reject_query.where(EntryDecisionRecord.symbol == symbol)
        if from_date:
            reject_query = reject_query.where(EntryDecisionRecord.timestamp >= from_date)
        if to_date:
            reject_query = reject_query.where(EntryDecisionRecord.timestamp <= to_date)
        reject_query = reject_query.group_by(EntryDecisionRecord.reject_reason)
        reject_result = await db.execute(reject_query)
        reject_breakdown = {
            str(row.reject_reason or "unknown"): int(row.count)
            for row in reject_result.all()
        }
        return {"funnel": funnel, "reject_breakdown": reject_breakdown}

    async def performance_by_regime(
        self,
        db: AsyncSession,
        *,
        symbol: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate from analytics_rollups when available, else trade_outcomes."""
        query = select(AnalyticsRollupRecord).where(
            AnalyticsRollupRecord.period_type == "regime"
        )
        if symbol:
            query = query.where(AnalyticsRollupRecord.symbol == symbol)
        result = await db.execute(query)
        rollups = result.scalars().all()
        if rollups:
            out = []
            for r in rollups:
                tc = int(r.trade_count or 0)
                wc = int(r.win_count or 0)
                out.append(
                    {
                        "regime": r.period_key,
                        "symbol": r.symbol,
                        "trade_count": tc,
                        "win_rate": wc / tc if tc else 0.0,
                        "total_pnl_usd": float(r.total_pnl_usd or 0),
                    }
                )
            return out

        rows = await self.list_trade_outcomes(
            db,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            limit=2000,
            offset=0,
        )
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            meta = row.get("metadata") or {}
            dc = meta.get("decision_context") or {}
            rb = dc.get("rule_based_pipeline") or {}
            ms = rb.get("market_state") or {}
            regime = str(ms.get("regime") or "unknown")
            b = buckets.setdefault(
                regime,
                {"regime": regime, "trade_count": 0, "win_count": 0, "total_pnl_usd": 0.0},
            )
            b["trade_count"] += 1
            pnl = float(row.get("pnl") or 0)
            b["total_pnl_usd"] += pnl
            if pnl > 0:
                b["win_count"] += 1
        for b in buckets.values():
            tc = b["trade_count"]
            b["win_rate"] = b["win_count"] / tc if tc else 0.0
        return list(buckets.values())

    async def performance_by_config(
        self,
        db: AsyncSession,
        *,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = select(AnalyticsRollupRecord).where(
            AnalyticsRollupRecord.period_type == "config_hash"
        )
        if symbol:
            query = query.where(AnalyticsRollupRecord.symbol == symbol)
        result = await db.execute(query)
        out = []
        for r in result.scalars().all():
            tc = int(r.trade_count or 0)
            wc = int(r.win_count or 0)
            out.append(
                {
                    "config_hash": r.period_key,
                    "symbol": r.symbol,
                    "trade_count": tc,
                    "win_rate": wc / tc if tc else 0.0,
                    "total_pnl_usd": float(r.total_pnl_usd or 0),
                }
            )
        return out

    async def list_rollups(
        self,
        db: AsyncSession,
        *,
        period_type: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = select(AnalyticsRollupRecord)
        if period_type:
            query = query.where(AnalyticsRollupRecord.period_type == period_type)
        if symbol:
            query = query.where(AnalyticsRollupRecord.symbol == symbol)
        query = query.order_by(desc(AnalyticsRollupRecord.updated_at)).limit(limit)
        result = await db.execute(query)
        return [
            {
                "period_type": r.period_type,
                "period_key": r.period_key,
                "symbol": r.symbol,
                "trade_count": int(r.trade_count or 0),
                "win_count": int(r.win_count or 0),
                "total_pnl_usd": float(r.total_pnl_usd or 0),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in result.scalars().all()
        ]

    @staticmethod
    def _trade_outcome_row(record: TradeOutcomeRecord) -> Dict[str, Any]:
        return {
            "position_id": record.position_id,
            "symbol": record.symbol,
            "side": record.side,
            "signal": record.signal,
            "entry_price": float(record.entry_price),
            "exit_price": float(record.exit_price),
            "quantity": float(record.quantity),
            "pnl": float(record.pnl or 0),
            "pnl_pct": float(record.pnl_pct) if record.pnl_pct is not None else None,
            "close_reason": record.close_reason,
            "opened_at": record.opened_at.isoformat() if record.opened_at else None,
            "closed_at": record.closed_at.isoformat() if record.closed_at else None,
            "metadata": record.metadata_json,
        }


analytics_service = AnalyticsService()
