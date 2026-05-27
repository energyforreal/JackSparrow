"""Shared hooks for deterministic self-awareness on position close."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_MEMORY_BACKFILL_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=50)
_RETRY_WORKER_STARTED = False
_MAX_BACKFILL_RETRIES = 3


async def _memory_backfill_worker() -> None:
    """Retry failed vector-memory outcome backfills with exponential backoff."""
    while True:
        item = await _MEMORY_BACKFILL_QUEUE.get()
        try:
            payload = item.get("payload") if isinstance(item, dict) else None
            attempt = int(item.get("attempt", 0)) if isinstance(item, dict) else 0
            if not isinstance(payload, dict):
                continue
            await _run_memory_backfill(payload)
        except Exception as e:
            attempt = int(item.get("attempt", 0)) if isinstance(item, dict) else 0
            payload = item.get("payload") if isinstance(item, dict) else None
            if isinstance(payload, dict) and attempt < _MAX_BACKFILL_RETRIES:
                delay = min(30.0, 2.0 ** attempt)
                await asyncio.sleep(delay)
                try:
                    _MEMORY_BACKFILL_QUEUE.put_nowait(
                        {"payload": payload, "attempt": attempt + 1}
                    )
                except asyncio.QueueFull:
                    logger.warning("memory_backfill_retry_queue_full")
            else:
                logger.warning(
                    "memory_backfill_retry_exhausted",
                    error=str(e),
                    attempt=attempt,
                )
        finally:
            _MEMORY_BACKFILL_QUEUE.task_done()


def _ensure_backfill_worker() -> None:
    global _RETRY_WORKER_STARTED
    if _RETRY_WORKER_STARTED:
        return
    try:
        asyncio.get_running_loop().create_task(_memory_backfill_worker())
        _RETRY_WORKER_STARTED = True
    except RuntimeError:
        pass


def _enqueue_memory_backfill(payload: Dict[str, Any]) -> None:
    _ensure_backfill_worker()
    try:
        _MEMORY_BACKFILL_QUEUE.put_nowait({"payload": dict(payload), "attempt": 0})
    except asyncio.QueueFull:
        logger.warning("memory_backfill_queue_full", symbol=payload.get("symbol"))


async def _run_memory_backfill(payload: Dict[str, Any]) -> None:
    memory_context_id = payload.get("memory_context_id")
    reasoning_chain_id = payload.get("reasoning_chain_id")
    pnl = float(payload.get("pnl") or 0)
    duration_seconds = float(payload.get("duration_seconds") or 0)
    exit_reason = str(payload.get("exit_reason") or "unknown")
    outcome = {
        "pnl": pnl,
        "exit_reason": exit_reason,
        "was_profitable": pnl > 0,
        "duration_seconds": duration_seconds,
        "closed_at": payload.get("timestamp"),
    }
    from agent.core.mcp_orchestrator import mcp_orchestrator

    store = getattr(mcp_orchestrator, "vector_store", None)
    if not store:
        return
    ctx = None
    if memory_context_id:
        ctx = await store.get_context_by_id(str(memory_context_id))
    if ctx is None and reasoning_chain_id:
        ctx = await store.find_context_by_reasoning_chain_id(str(reasoning_chain_id))
    if ctx is not None:
        await store.update_context_outcome(ctx.context_id, outcome)
        payload["memory_context_id"] = ctx.context_id


async def enrich_position_closed_payload(payload: Dict[str, Any]) -> None:
    """Backfill memory outcomes and attach advisory reflection to close payload."""
    if not isinstance(payload, dict):
        return

    memory_context_id = payload.get("memory_context_id")
    reasoning_chain_id = payload.get("reasoning_chain_id")
    pnl = float(payload.get("pnl") or 0)
    duration_seconds = float(payload.get("duration_seconds") or 0)
    exit_reason = str(payload.get("exit_reason") or "unknown")
    outcome = {
        "pnl": pnl,
        "exit_reason": exit_reason,
        "was_profitable": pnl > 0,
        "duration_seconds": duration_seconds,
        "closed_at": payload.get("timestamp"),
    }

    if getattr(settings, "agent_memory_outcome_backfill_enabled", True):
        try:
            await _run_memory_backfill(payload)
        except Exception as e:
            logger.warning(
                "position_closed_memory_backfill_failed",
                error=str(e),
                exc_info=True,
            )
            _enqueue_memory_backfill(payload)

    if getattr(settings, "agent_reflection_advisory_enabled", True):
        try:
            from agent.core.agent_reflection_engine import reflect_on_trade

            intro = payload.get("agent_introspection_at_entry")
            reflection = reflect_on_trade(
                symbol=str(payload.get("symbol") or ""),
                position_id=str(payload.get("position_id") or ""),
                predicted_signal=str(payload.get("predicted_signal") or ""),
                pnl=pnl,
                exit_reason=exit_reason,
                confidence_at_entry=payload.get("confidence_at_entry"),
                policy_reason_codes=(
                    intro.get("policy_reason_codes")
                    if isinstance(intro, dict)
                    else None
                ),
                introspection_at_entry=intro if isinstance(intro, dict) else None,
                advisory_only=True,
            )
            payload["reflection_snapshot"] = reflection.to_dict()
        except Exception as e:
            logger.warning(
                "position_closed_reflection_failed",
                error=str(e),
                exc_info=True,
            )
