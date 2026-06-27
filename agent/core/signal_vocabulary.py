"""Canonical trading-signal vocabulary for JackSparrow.

Entry signals use **long/short** labels (``LONG``, ``SHORT``, ``STRONG_LONG``,
``STRONG_SHORT``). Legacy ``BUY``/``SELL`` aliases are accepted at boundaries
and normalized to the canonical form.

Exchange order placement still uses lowercase ``buy``/``sell``; open positions
use lowercase ``long``/``short``.
"""

from __future__ import annotations

from typing import Any, FrozenSet, Optional

# Canonical discrete signals (event bus, policy, UI).
CANONICAL_SIGNALS: FrozenSet[str] = frozenset(
    {"STRONG_LONG", "LONG", "HOLD", "SHORT", "STRONG_SHORT"}
)

ENTRY_LONG_SIGNALS: FrozenSet[str] = frozenset({"LONG", "STRONG_LONG"})
ENTRY_SHORT_SIGNALS: FrozenSet[str] = frozenset({"SHORT", "STRONG_SHORT"})
ENTRY_SIGNALS: FrozenSet[str] = ENTRY_LONG_SIGNALS | ENTRY_SHORT_SIGNALS

# Legacy aliases accepted at API / persistence boundaries.
_LEGACY_LONG: FrozenSet[str] = frozenset({"BUY", "STRONG_BUY"})
_LEGACY_SHORT: FrozenSet[str] = frozenset({"SELL", "STRONG_SELL"})
_LEGACY_ENTRY: FrozenSet[str] = _LEGACY_LONG | _LEGACY_SHORT

_LEGACY_TO_CANONICAL: dict[str, str] = {
    "BUY": "LONG",
    "STRONG_BUY": "STRONG_LONG",
    "SELL": "SHORT",
    "STRONG_SELL": "STRONG_SHORT",
}

_CANONICAL_TO_LEGACY: dict[str, str] = {
    "LONG": "BUY",
    "STRONG_LONG": "STRONG_BUY",
    "SHORT": "SELL",
    "STRONG_SHORT": "STRONG_SELL",
}


def normalize_signal(signal: Any, *, default: str = "HOLD") -> str:
    """Normalize any signal label to canonical LONG/SHORT/HOLD vocabulary."""
    if signal is None:
        return default
    s = str(signal).strip().upper()
    if s in CANONICAL_SIGNALS:
        return s
    if s in _LEGACY_TO_CANONICAL:
        return _LEGACY_TO_CANONICAL[s]
    return default


def to_legacy_signal(signal: Any, *, default: str = "HOLD") -> str:
    """Map canonical signal to legacy BUY/SELL label (DB / external APIs)."""
    canon = normalize_signal(signal, default=default)
    if canon in _CANONICAL_TO_LEGACY:
        return _CANONICAL_TO_LEGACY[canon]
    return canon


def is_entry_signal(signal: Any) -> bool:
    return normalize_signal(signal) in ENTRY_SIGNALS


def is_long_signal(signal: Any) -> bool:
    return normalize_signal(signal) in ENTRY_LONG_SIGNALS


def is_short_signal(signal: Any) -> bool:
    return normalize_signal(signal) in ENTRY_SHORT_SIGNALS


def same_direction(signal_a: Any, signal_b: Any) -> bool:
    a = normalize_signal(signal_a)
    b = normalize_signal(signal_b)
    if a in ENTRY_LONG_SIGNALS and b in ENTRY_LONG_SIGNALS:
        return True
    if a in ENTRY_SHORT_SIGNALS and b in ENTRY_SHORT_SIGNALS:
        return True
    return False


def signal_to_position_side(signal: Any) -> Optional[str]:
    """Map entry signal to lowercase position side ``long`` or ``short``."""
    canon = normalize_signal(signal)
    if canon in ENTRY_LONG_SIGNALS:
        return "long"
    if canon in ENTRY_SHORT_SIGNALS:
        return "short"
    return None


def parse_entry_side(side_raw: Any) -> Optional[str]:
    """Normalize RiskApproved / trade side to lowercase ``long`` or ``short``."""
    if side_raw is None:
        return "long"
    s = str(side_raw).strip().lower()
    if s in ("long", "buy"):
        return "long"
    if s in ("short", "sell"):
        return "short"
    upper = s.upper()
    if upper in ENTRY_LONG_SIGNALS or upper in _LEGACY_LONG:
        return "long"
    if upper in ENTRY_SHORT_SIGNALS or upper in _LEGACY_SHORT:
        return "short"
    return None


def position_side_to_order_side(position_side: str) -> str:
    """Map position side to exchange order side."""
    s = str(position_side or "long").strip().lower()
    return "sell" if s == "short" else "buy"


def position_side_to_sl_side(position_side: str) -> str:
    """Map position side to SL/TP side token (``LONG`` or ``SHORT``)."""
    s = str(position_side or "long").strip().lower()
    return "SHORT" if s == "short" else "LONG"


def signal_from_side_and_confidence(side: str, confidence: float) -> str:
    """Derive canonical entry signal from direction + confidence."""
    s = str(side or "").upper()
    if s in ("LONG", "BUY"):
        return "STRONG_LONG" if confidence >= 0.85 else "LONG"
    if s in ("SHORT", "SELL"):
        return "STRONG_SHORT" if confidence >= 0.85 else "SHORT"
    return "HOLD"
