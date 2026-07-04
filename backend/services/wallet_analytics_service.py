"""Read-only analytics over synced wallet_transactions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import WalletTransactionRecord

import structlog

logger = structlog.get_logger()


class WalletAnalyticsService:
    """Query wallet ledger and cost rollups from PostgreSQL."""

    async def list_wallet_ledger(
        self,
        db: AsyncSession,
        *,
        transaction_type: Optional[str] = None,
        asset_symbol: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = select(WalletTransactionRecord)
        if transaction_type:
            query = query.where(
                WalletTransactionRecord.transaction_type == transaction_type.lower()
            )
        if asset_symbol:
            query = query.where(
                WalletTransactionRecord.asset_symbol == asset_symbol.upper()
            )
        if from_date:
            query = query.where(WalletTransactionRecord.occurred_at >= from_date)
        if to_date:
            query = query.where(WalletTransactionRecord.occurred_at <= to_date)
        query = (
            query.order_by(desc(WalletTransactionRecord.occurred_at))
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(query)
        rows = result.scalars().all()
        return [self._wallet_row(r) for r in rows]

    async def funding_summary(
        self,
        db: AsyncSession,
        *,
        period: str = "week",
        asset_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now - timedelta(days=30)
        else:
            start = now - timedelta(days=7)

        clauses = [
            WalletTransactionRecord.occurred_at >= start,
            WalletTransactionRecord.transaction_type == "funding",
        ]
        if asset_symbol:
            clauses.append(WalletTransactionRecord.asset_symbol == asset_symbol.upper())

        query = select(
            func.count(WalletTransactionRecord.id),
            func.coalesce(func.sum(WalletTransactionRecord.amount), 0),
        ).where(*clauses)
        result = await db.execute(query)
        count, total = result.one()
        return {
            "period": period,
            "asset_symbol": asset_symbol,
            "funding_event_count": int(count or 0),
            "funding_total": float(total or 0),
            "from_date": start.isoformat(),
            "to_date": now.isoformat(),
        }

    async def cost_breakdown(
        self,
        db: AsyncSession,
        *,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        query = select(
            WalletTransactionRecord.transaction_type,
            func.coalesce(func.sum(WalletTransactionRecord.amount), 0),
            func.count(WalletTransactionRecord.id),
        )
        if from_date:
            query = query.where(WalletTransactionRecord.occurred_at >= from_date)
        if to_date:
            query = query.where(WalletTransactionRecord.occurred_at <= to_date)
        query = query.group_by(WalletTransactionRecord.transaction_type)
        result = await db.execute(query)
        breakdown: Dict[str, Any] = {}
        for tx_type, total, count in result.all():
            key = str(tx_type or "unknown")
            breakdown[key] = {
                "total": float(total or 0),
                "count": int(count or 0),
            }
        commission = float(breakdown.get("commission", {}).get("total", 0))
        funding = float(breakdown.get("funding", {}).get("total", 0))
        rebates = float(breakdown.get("commission_rebate", {}).get("total", 0))
        return {
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "commission_usd": commission,
            "funding_usd": funding,
            "rebates_usd": rebates,
            "net_wallet_impact_usd": commission + funding + rebates,
            "by_type": breakdown,
        }

    @staticmethod
    def _wallet_row(row: WalletTransactionRecord) -> Dict[str, Any]:
        return {
            "id": row.id,
            "exchange": row.exchange,
            "exchange_transaction_id": row.exchange_transaction_id,
            "transaction_type": row.transaction_type,
            "asset_symbol": row.asset_symbol,
            "product_id": row.product_id,
            "order_id": row.order_id,
            "amount": float(row.amount) if row.amount is not None else None,
            "balance_after": float(row.balance_after)
            if row.balance_after is not None
            else None,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "metadata": row.metadata_json,
        }


wallet_analytics_service = WalletAnalyticsService()
