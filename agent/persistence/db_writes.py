"""
Non-blocking PostgreSQL writes for observability tables.

Uses sync SQLAlchemy + asyncio.to_thread so the agent does not require asyncpg.
Failures are logged and never raise into the trading path.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

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
    denorm: Optional[Dict[str, Any]] = None,
) -> None:
    engine = _get_engine(database_url)
    meta_json = json.dumps(metadata if metadata is not None else {})
    d = denorm if isinstance(denorm, dict) else {}
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO trade_outcomes (
                    position_id, symbol, side, signal,
                    entry_price, exit_price, quantity, pnl, pnl_pct,
                    close_reason, opened_at, closed_at, metadata,
                    config_hash, setup_type, regime, root_cause,
                    entry_quality_score, mfe_pct, mae_pct, slippage_bps_entry,
                    decision_event_count
                ) VALUES (
                    :position_id, :symbol, :side, :signal,
                    :entry_price, :exit_price, :quantity, :pnl, :pnl_pct,
                    :close_reason, :opened_at, :closed_at, (:metadata)::jsonb,
                    :config_hash, :setup_type, :regime, :root_cause,
                    :entry_quality_score, :mfe_pct, :mae_pct, :slippage_bps_entry,
                    :decision_event_count
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
                "config_hash": d.get("config_hash"),
                "setup_type": d.get("setup_type"),
                "regime": d.get("regime"),
                "root_cause": d.get("root_cause"),
                "entry_quality_score": d.get("entry_quality_score"),
                "mfe_pct": d.get("mfe_pct"),
                "mae_pct": d.get("mae_pct"),
                "slippage_bps_entry": d.get("slippage_bps_entry"),
                "decision_event_count": d.get("decision_event_count"),
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
    denorm: Optional[Dict[str, Any]] = None,
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
            denorm=denorm,
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


def _insert_entry_decision_sync(
    database_url: str,
    *,
    decision_id: str,
    symbol: str,
    timestamp: datetime,
    outcome: str,
    reject_reason: Optional[str],
    signal: Optional[str],
    side: Optional[str],
    confidence: Optional[float],
    reasoning_chain_id: Optional[str],
    config_hash: Optional[str],
    position_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> None:
    engine = _get_engine(database_url)
    meta_json = json.dumps(metadata if metadata is not None else {})
    conf_dec = Decimal(str(round(confidence, 6))) if confidence is not None else None
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entry_decisions (
                    decision_id, symbol, timestamp, outcome, reject_reason,
                    signal, side, confidence, reasoning_chain_id, config_hash,
                    position_id, metadata
                ) VALUES (
                    :decision_id, :symbol, :timestamp, :outcome, :reject_reason,
                    :signal, :side, :confidence, :reasoning_chain_id, :config_hash,
                    :position_id, (:metadata)::jsonb
                )
                ON CONFLICT (decision_id) DO UPDATE SET
                    outcome = EXCLUDED.outcome,
                    position_id = COALESCE(EXCLUDED.position_id, entry_decisions.position_id),
                    metadata = EXCLUDED.metadata
                """
            ),
            {
                "decision_id": decision_id,
                "symbol": symbol,
                "timestamp": timestamp,
                "outcome": outcome,
                "reject_reason": reject_reason,
                "signal": signal,
                "side": side,
                "confidence": conf_dec,
                "reasoning_chain_id": reasoning_chain_id,
                "config_hash": config_hash,
                "position_id": position_id,
                "metadata": meta_json,
            },
        )
        conn.commit()


async def persist_entry_decision_async(
    database_url: str,
    *,
    decision_id: str,
    symbol: str,
    outcome: str,
    reject_reason: Optional[str] = None,
    signal: Optional[str] = None,
    side: Optional[str] = None,
    confidence: Optional[float] = None,
    reasoning_chain_id: Optional[str] = None,
    config_hash: Optional[str] = None,
    position_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> None:
    """Insert or update one entry_decisions row."""

    ts = timestamp or datetime.now(timezone.utc)

    def _run() -> None:
        _insert_entry_decision_sync(
            database_url,
            decision_id=decision_id,
            symbol=symbol,
            timestamp=ts,
            outcome=outcome,
            reject_reason=reject_reason,
            signal=signal,
            side=side,
            confidence=confidence,
            reasoning_chain_id=reasoning_chain_id,
            config_hash=config_hash,
            position_id=position_id,
            metadata=metadata,
        )

    try:
        await asyncio.to_thread(_run)
        logger.debug(
            "entry_decision_persisted",
            decision_id=decision_id,
            symbol=symbol,
            outcome=outcome,
        )
    except Exception as e:
        logger.warning(
            "entry_decision_persist_failed",
            decision_id=decision_id,
            symbol=symbol,
            error=str(e),
            exc_info=True,
        )


def _upsert_analytics_rollup_sync(
    database_url: str,
    *,
    period_type: str,
    period_key: str,
    symbol: str,
    pnl_usd: float,
    won: bool,
) -> None:
    engine = _get_engine(database_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analytics_rollups (
                    period_type, period_key, symbol,
                    trade_count, win_count, total_pnl_usd, updated_at
                ) VALUES (
                    :period_type, :period_key, :symbol,
                    1, :win_count, :pnl_usd, NOW()
                )
                ON CONFLICT (period_type, period_key, symbol)
                DO UPDATE SET
                    trade_count = analytics_rollups.trade_count + 1,
                    win_count = analytics_rollups.win_count + EXCLUDED.win_count,
                    total_pnl_usd = analytics_rollups.total_pnl_usd + EXCLUDED.total_pnl_usd,
                    updated_at = NOW()
                """
            ),
            {
                "period_type": period_type,
                "period_key": period_key,
                "symbol": symbol,
                "win_count": 1 if won else 0,
                "pnl_usd": pnl_usd,
            },
        )
        conn.commit()


async def persist_analytics_rollups_async(
    database_url: str,
    *,
    symbol: str,
    pnl_usd: float,
    closed_at: datetime,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Increment rollup buckets for a closed trade."""
    won = float(pnl_usd or 0) > 0
    day_key = closed_at.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = closed_at.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"

    meta = metadata if isinstance(metadata, dict) else {}
    dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
    mstate = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    sys_ctx = meta.get("system_context") if isinstance(meta.get("system_context"), dict) else {}

    buckets = [
        ("daily", day_key),
        ("weekly", week_key),
        ("regime", str(mstate.get("regime") or "unknown")),
        ("setup_type", str(gates.get("setup_type") or "none")),
    ]
    cfg_hash = sys_ctx.get("config_hash")
    if cfg_hash:
        buckets.append(("config_hash", str(cfg_hash)))

    def _run() -> None:
        for period_type, period_key in buckets:
            _upsert_analytics_rollup_sync(
                database_url,
                period_type=period_type,
                period_key=period_key,
                symbol=symbol,
                pnl_usd=float(pnl_usd or 0),
                won=won,
            )

    try:
        await asyncio.to_thread(_run)
    except Exception as e:
        logger.warning(
            "analytics_rollup_persist_failed",
            symbol=symbol,
            error=str(e),
            exc_info=True,
        )


def _insert_decision_event_sync(
    database_url: str,
    *,
    event_id: str,
    position_id: Optional[str],
    reasoning_chain_id: Optional[str],
    symbol: str,
    event_type: str,
    bar_index: Optional[int],
    sequence_num: int,
    captured_at: datetime,
    caused_by: Optional[List[str]],
    delta: Optional[Dict[str, Any]],
    payload: Optional[Dict[str, Any]],
) -> None:
    engine = _get_engine(database_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO trade_decision_events (
                    event_id, position_id, reasoning_chain_id, symbol,
                    event_type, bar_index, sequence_num, captured_at,
                    caused_by, delta, payload
                ) VALUES (
                    :event_id, :position_id, :reasoning_chain_id, :symbol,
                    :event_type, :bar_index, :sequence_num, :captured_at,
                    (:caused_by)::jsonb, (:delta)::jsonb, (:payload)::jsonb
                )
                """
            ),
            {
                "event_id": event_id,
                "position_id": position_id,
                "reasoning_chain_id": reasoning_chain_id,
                "symbol": symbol,
                "event_type": event_type,
                "bar_index": bar_index,
                "sequence_num": sequence_num,
                "captured_at": captured_at,
                "caused_by": json.dumps(caused_by or []),
                "delta": json.dumps(delta if delta is not None else {}),
                "payload": json.dumps(payload if payload is not None else {}),
            },
        )
        conn.commit()


async def persist_decision_event_async(
    database_url: str,
    *,
    event_id: str,
    position_id: Optional[str],
    reasoning_chain_id: Optional[str],
    symbol: str,
    event_type: str,
    bar_index: Optional[int],
    sequence_num: int,
    captured_at: datetime,
    caused_by: Optional[List[str]] = None,
    delta: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert one trade_decision_events row."""

    def _run() -> None:
        _insert_decision_event_sync(
            database_url,
            event_id=event_id,
            position_id=position_id,
            reasoning_chain_id=reasoning_chain_id,
            symbol=symbol,
            event_type=event_type,
            bar_index=bar_index,
            sequence_num=sequence_num,
            captured_at=captured_at,
            caused_by=caused_by,
            delta=delta,
            payload=payload,
        )

    try:
        await asyncio.to_thread(_run)
    except Exception as e:
        logger.warning(
            "decision_event_persist_failed",
            event_id=event_id,
            symbol=symbol,
            error=str(e),
            exc_info=True,
        )


def _insert_entry_decision_label_sync(
    database_url: str,
    *,
    decision_id: str,
    label_horizon_bars: int,
    forward_return_pct: Optional[float],
    forward_mfe_pct: Optional[float],
    forward_mae_pct: Optional[float],
    would_have_won: Optional[bool],
    labeled_at: datetime,
) -> None:
    engine = _get_engine(database_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entry_decision_labels (
                    decision_id, label_horizon_bars, forward_return_pct,
                    forward_mfe_pct, forward_mae_pct, would_have_won, labeled_at
                ) VALUES (
                    :decision_id, :label_horizon_bars, :forward_return_pct,
                    :forward_mfe_pct, :forward_mae_pct, :would_have_won, :labeled_at
                )
                ON CONFLICT (decision_id) DO UPDATE SET
                    forward_return_pct = EXCLUDED.forward_return_pct,
                    forward_mfe_pct = EXCLUDED.forward_mfe_pct,
                    forward_mae_pct = EXCLUDED.forward_mae_pct,
                    would_have_won = EXCLUDED.would_have_won,
                    labeled_at = EXCLUDED.labeled_at
                """
            ),
            {
                "decision_id": decision_id,
                "label_horizon_bars": label_horizon_bars,
                "forward_return_pct": forward_return_pct,
                "forward_mfe_pct": forward_mfe_pct,
                "forward_mae_pct": forward_mae_pct,
                "would_have_won": would_have_won,
                "labeled_at": labeled_at,
            },
        )
        conn.commit()


async def persist_entry_decision_label_async(
    database_url: str,
    *,
    decision_id: str,
    label_horizon_bars: int,
    forward_return_pct: Optional[float] = None,
    forward_mfe_pct: Optional[float] = None,
    forward_mae_pct: Optional[float] = None,
    would_have_won: Optional[bool] = None,
    labeled_at: Optional[datetime] = None,
) -> None:
    """Insert or update one entry_decision_labels row."""

    ts = labeled_at or datetime.now(timezone.utc)

    def _run() -> None:
        _insert_entry_decision_label_sync(
            database_url,
            decision_id=decision_id,
            label_horizon_bars=label_horizon_bars,
            forward_return_pct=forward_return_pct,
            forward_mfe_pct=forward_mfe_pct,
            forward_mae_pct=forward_mae_pct,
            would_have_won=would_have_won,
            labeled_at=ts,
        )

    try:
        await asyncio.to_thread(_run)
    except Exception as e:
        logger.warning(
            "entry_decision_label_persist_failed",
            decision_id=decision_id,
            error=str(e),
            exc_info=True,
        )
