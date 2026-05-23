"""Runtime v43 horizon profile cache (updated each orchestrator prediction cycle)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.core.config import settings
from feature_store.jacksparrow_v43_horizon import V43HorizonProfile, horizon_profile

_last_profile: Optional[V43HorizonProfile] = None
_last_execution_profile: Dict[str, Any] = {}


def set_runtime_v43_horizon(
    forward_bars: int,
    *,
    execution_profile: Optional[Dict[str, Any]] = None,
) -> None:
    global _last_profile, _last_execution_profile
    _last_profile = horizon_profile(forward_bars)
    _last_execution_profile = dict(execution_profile or {})


def get_runtime_v43_horizon() -> Optional[V43HorizonProfile]:
    return _last_profile


def get_runtime_v43_execution_profile() -> Dict[str, Any]:
    return dict(_last_execution_profile)


def effective_v43_trade_debounce_bars() -> int:
    if bool(getattr(settings, "jacksparrow_v43_align_execution_to_horizon", True)):
        prof = get_runtime_v43_execution_profile()
        if prof.get("enabled") and prof.get("trade_debounce_bars") is not None:
            return int(prof["trade_debounce_bars"])
    return int(getattr(settings, "jacksparrow_v43_trade_debounce_bars", 3) or 3)


def effective_max_position_hold_hours() -> float:
    if bool(getattr(settings, "jacksparrow_v43_align_execution_to_horizon", True)):
        prof = get_runtime_v43_execution_profile()
        if prof.get("enabled") and prof.get("max_position_hold_hours") is not None:
            return float(prof["max_position_hold_hours"])
    return float(getattr(settings, "max_position_hold_hours", 24) or 24)
