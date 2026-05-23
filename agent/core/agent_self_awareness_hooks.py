"""Shared hooks for deterministic self-awareness on position close."""

from __future__ import annotations

from typing import Any, Dict

import structlog

from agent.core.config import settings

logger = structlog.get_logger()


async def enrich_position_closed_payload(payload: Dict[str, Any]) -> None:
    """Backfill memory outcomes and attach advisory reflection to close payload."""
    if not isinstance(payload, dict):
        return

    memory_context_id = payload.get("memory_context_id")
    reasoning_chain_id = payload.get("reasoning_chain_id")
    pnl = float(payload.get("pnl") or 0)
    duration_seconds = float(payload.get("duration_seconds") or 0)
    exit_reason = str(payload.get("exit_reason") or "unknown")
    was_profitable = pnl > 0
    outcome = {
        "pnl": pnl,
        "exit_reason": exit_reason,
        "was_profitable": was_profitable,
        "duration_seconds": duration_seconds,
        "closed_at": payload.get("timestamp"),
    }

    if getattr(settings, "agent_memory_outcome_backfill_enabled", True):
        try:
            from agent.core.mcp_orchestrator import mcp_orchestrator

            store = getattr(mcp_orchestrator, "vector_store", None)
            if store:
                ctx = None
                if memory_context_id:
                    ctx = await store.get_context_by_id(str(memory_context_id))
                if ctx is None and reasoning_chain_id:
                    ctx = await store.find_context_by_reasoning_chain_id(
                        str(reasoning_chain_id)
                    )
                if ctx is not None:
                    await store.update_context_outcome(ctx.context_id, outcome)
                    payload["memory_context_id"] = ctx.context_id
        except Exception as e:
            logger.warning(
                "position_closed_memory_backfill_failed",
                error=str(e),
                exc_info=True,
            )

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
