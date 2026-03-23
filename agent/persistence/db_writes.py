"""
Non-blocking PostgreSQL writes for observability tables.

Uses sync SQLAlchemy + asyncio.to_thread so the agent does not require asyncpg.
Failures are logged and never raise into the trading path.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

logger = structlog.get_logger()

_engine: Optional[Engine] = None


def _sync_database_url(url: str) -> str:
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _get_engine(database_url: str) -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            _sync_database_url(database_url),
            poolclass=NullPool,
            pool_pre_ping=True,
        )
    return _engine


def _insert_prediction_audit_sync(
    database_url: str,
    *,
    request_id: str,
    symbol: str,
    confidence: Optional[float],
    latency_ms: Optional[float],
    source: str,
    model_version: Optional[str],
    outcome_reference: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> None:
    engine = _get_engine(database_url)
    conf_dec = Decimal(str(round(confidence, 4))) if confidence is not None else None
    lat_dec = Decimal(str(round(latency_ms, 2))) if latency_ms is not None else None
    meta_json = json.dumps(metadata if metadata is not None else {})
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO prediction_audit (
                    request_id, model_version, symbol, confidence, latency_ms,
                    source, outcome_reference, metadata
                ) VALUES (
                    :request_id, :model_version, :symbol, :confidence, :latency_ms,
                    :source, :outcome_reference, (:metadata)::jsonb
                )
                """
            ),
            {
                "request_id": request_id,
                "model_version": model_version,
                "symbol": symbol,
                "confidence": conf_dec,
                "latency_ms": lat_dec,
                "source": source,
                "outcome_reference": outcome_reference,
                "metadata": meta_json,
            },
        )
        conn.commit()


def _insert_trade_outcome_sync(
    database_url: str,
    *,
    position_id: Optional[str],
    symbol: str,
    side: Optional[str],
    signal: Optional[str],
    entry_price: float,
    exit_price: float,
    quantity: float,
    pnl: float,
    pnl_pct: Optional[float],
    close_reason: Optional[str],
    opened_at: Optional[datetime],
    closed_at: datetime,
    metadata: Optional[Dict[str, Any]],
) -> None:
    engine = _get_engine(database_url)
    meta_json = json.dumps(metadata if metadata is not None else {})
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO trade_outcomes (
                    position_id, symbol, side, signal,
                    entry_price, exit_price, quantity, pnl, pnl_pct,
                    close_reason, opened_at, closed_at, metadata
                ) VALUES (
                    :position_id, :symbol, :side, :signal,
                    :entry_price, :exit_price, :quantity, :pnl, :pnl_pct,
                    :close_reason, :opened_at, :closed_at, (:metadata)::jsonb
                )
                """
            ),
            {
                "position_id": position_id,
                "symbol": symbol,
                "side": side,
                "signal": signal,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "close_reason": close_reason,
                "opened_at": opened_at,
                "closed_at": closed_at,
                "metadata": meta_json,
            },
        )
        conn.commit()


async def persist_prediction_audit_async(
    database_url: str,
    *,
    symbol: str,
    confidence: Optional[float],
    latency_ms: Optional[float],
    source: str = "agent_mcp",
    model_version: Optional[str] = None,
    outcome_reference: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> None:
    """Insert one prediction_audit row (fire-and-forget safe when wrapped)."""
    rid = request_id or str(uuid.uuid4())

    def _run() -> None:
        _insert_prediction_audit_sync(
            database_url,
            request_id=rid,
            symbol=symbol,
            confidence=confidence,
            latency_ms=latency_ms,
            source=source,
            model_version=model_version,
            outcome_reference=outcome_reference,
            metadata=metadata,
        )

    try:
        await asyncio.to_thread(_run)
        logger.debug(
            "prediction_audit_persisted",
            request_id=rid,
            symbol=symbol,
            source=source,
        )
    except Exception as e:
        logger.warning(
            "prediction_audit_persist_failed",
            request_id=rid,
            symbol=symbol,
            error=str(e),
            exc_info=True,
        )


async def persist_trade_outcome_async(
    database_url: str,
    *,
    position_id: Optional[str],
    symbol: str,
    side: Optional[str],
    signal: Optional[str],
    entry_price: float,
    exit_price: float,
    quantity: float,
    pnl: float,
    pnl_pct: Optional[float],
    close_reason: Optional[str],
    opened_at: Optional[datetime],
    closed_at: datetime,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert one trade_outcomes row."""

    def _run() -> None:
        _insert_trade_outcome_sync(
            database_url,
            position_id=position_id,
            symbol=symbol,
            side=side,
            signal=signal,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            close_reason=close_reason,
            opened_at=opened_at,
            closed_at=closed_at,
            metadata=metadata,
        )

    try:
        await asyncio.to_thread(_run)
        logger.debug(
            "trade_outcome_persisted",
            position_id=position_id,
            symbol=symbol,
        )
    except Exception as e:
        logger.warning(
            "trade_outcome_persist_failed",
            position_id=position_id,
            symbol=symbol,
            error=str(e),
            exc_info=True,
        )
