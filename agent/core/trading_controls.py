"""Global trading halt controls: kill switch, exchange circuit breaker gate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_kill_switch_active: bool = False
_kill_switch_reason: Optional[str] = None
_kill_switch_set_at: Optional[datetime] = None


def is_kill_switch_active() -> bool:
    """True when env TRADING_KILL_SWITCH or runtime emergency halt is active."""
    if _kill_switch_active:
        return True
    return bool(getattr(settings, "trading_kill_switch", False))


def get_kill_switch_reason() -> str:
    if _kill_switch_reason:
        return _kill_switch_reason
    if bool(getattr(settings, "trading_kill_switch", False)):
        return "TRADING_KILL_SWITCH environment flag is enabled"
    return "Trading kill switch active"


def activate_kill_switch(reason: str, *, persist_context: bool = True) -> None:
    """Activate runtime kill switch (e.g. emergency stop)."""
    global _kill_switch_active, _kill_switch_reason, _kill_switch_set_at
    _kill_switch_active = True
    _kill_switch_reason = reason
    _kill_switch_set_at = datetime.now(timezone.utc)
    logger.critical("trading_kill_switch_activated", reason=reason)
    if persist_context:
        try:
            from agent.core.context_manager import context_manager

            context_manager.current_state.emergency_stop = True
            context_manager.current_state.trading_enabled = False
        except Exception as exc:
            logger.warning("kill_switch_context_update_failed", error=str(exc))


def clear_kill_switch() -> None:
    """Clear runtime kill switch (does not clear env TRADING_KILL_SWITCH)."""
    global _kill_switch_active, _kill_switch_reason, _kill_switch_set_at
    _kill_switch_active = False
    _kill_switch_reason = None
    _kill_switch_set_at = None


def trading_halt_status(delta_client: Any = None) -> Dict[str, Any]:
    """Aggregate halt reasons for health endpoints and logs."""
    reasons: list[str] = []
    if is_kill_switch_active():
        reasons.append(get_kill_switch_reason())
    if delta_client is not None and exchange_circuit_breaker_open(delta_client):
        reasons.append("Delta API circuit breaker is OPEN")
    return {
        "halted": bool(reasons),
        "reasons": reasons,
        "kill_switch_active": is_kill_switch_active(),
        "circuit_breaker_open": (
            exchange_circuit_breaker_open(delta_client) if delta_client is not None else None
        ),
    }


def exchange_circuit_breaker_open(delta_client: Any) -> bool:
    """True when Delta client circuit breaker blocks API calls."""
    if not bool(getattr(settings, "halt_trading_on_circuit_breaker", True)):
        return False
    try:
        from agent.data.delta_client import CircuitBreakerState

        state = getattr(getattr(delta_client, "circuit_breaker", None), "state", None)
        return state == CircuitBreakerState.OPEN
    except Exception:
        return False


def should_block_new_orders(delta_client: Any = None) -> tuple[bool, str]:
    """Fail-closed gate before risk-approved execution."""
    if is_kill_switch_active():
        return True, get_kill_switch_reason()
    if delta_client is not None and exchange_circuit_breaker_open(delta_client):
        return True, "Delta API circuit breaker open — new orders blocked"
    return False, ""
