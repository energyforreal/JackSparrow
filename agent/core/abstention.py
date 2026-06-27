"""Abstention taxonomy — HOLD reasons for hard tier only."""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, List, Optional


class AbstentionReason(str, Enum):
    """Why the agent abstained from entry (execution signal HOLD)."""

    NO_EDGE = "NO_EDGE"
    RISK_BLOCKED = "RISK_BLOCKED"
    POSITION_EXISTS = "POSITION_EXISTS"
    INVALID_DATA = "INVALID_DATA"
    EXCHANGE_DOWN = "EXCHANGE_DOWN"
    FORCE_HOLD = "FORCE_HOLD"
    OPERATIONAL = "OPERATIONAL"
    UNKNOWN = "UNKNOWN"


_HARD_PREFIXES = (
    "thesis_open_position",
    "thesis_market_health",
    "portfolio_guard",
    "agent_policy_force_hold",
    "insufficient_",
    "invalid_",
    "delta_client",
    "open_position",
    "freq_",
    "debounce",
)

_SOFT_PREFIXES = (
    "trade_score_below",
    "state_head_",
    "mso_liquidity_veto",
    "mso_trend_regime",
    "thesis_chop",
    "thesis_liquidity",
    "thesis_atr",
    "thesis_funding",
    "min_edge",
    "high_uncertainty",
)


def classify_abstention(
    reason_codes: Iterable[str],
    *,
    gate_reject: Optional[str] = None,
    signal: str = "HOLD",
) -> Optional[AbstentionReason]:
    """Map reason_codes to abstention enum; None when not a HOLD abstention."""
    if str(signal or "HOLD").upper() not in ("HOLD",):
        return None
    codes = [str(c) for c in (reason_codes or [])]
    joined = " ".join(codes).lower()
    gr = str(gate_reject or "").lower()

    if any("agent_policy_force_hold" in c for c in codes):
        return AbstentionReason.FORCE_HOLD
    if any("thesis_open_position" in c or "open_position" in c for c in codes):
        return AbstentionReason.POSITION_EXISTS
    if any("market_health" in c or "non_operational" in c for c in codes):
        return AbstentionReason.EXCHANGE_DOWN
    if any("portfolio_guard" in c or "portfolio" in c.lower() for c in codes):
        return AbstentionReason.RISK_BLOCKED
    if gr in ("open_position",) or "open_position" in joined:
        return AbstentionReason.POSITION_EXISTS
    if "insufficient" in joined or "invalid_data" in joined:
        return AbstentionReason.INVALID_DATA
    if any(c.startswith("freq_") or "debounce" in c for c in codes):
        return AbstentionReason.OPERATIONAL
    if any("conviction_below_entry_floor" in c or "no_edge" in c for c in codes):
        return AbstentionReason.NO_EDGE
    if any("fusion_ml_and_thesis_no_agreement" in c for c in codes):
        return AbstentionReason.NO_EDGE

    if any(any(c.startswith(p) for p in _SOFT_PREFIXES) for c in codes):
        return None

    if str(signal).upper() == "HOLD":
        return AbstentionReason.NO_EDGE
    return AbstentionReason.UNKNOWN


def abstention_from_reason_codes(
    reason_codes: List[str],
    *,
    gate_reject: Optional[str] = None,
    signal: str = "HOLD",
) -> Optional[str]:
    """Return abstention string for PolicyVerdict or None."""
    r = classify_abstention(reason_codes, gate_reject=gate_reject, signal=signal)
    return r.value if r else None
