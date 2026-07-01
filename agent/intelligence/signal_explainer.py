"""Deterministic signal explainability for trade snapshots and audits."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_GATE_LABELS = {
    "trend": "trend_confirmed",
    "structure": "structure_valid",
    "breakout": "breakout_confirmed",
    "liquidity": "liquidity_ok",
    "volatility": "volatility_suitable",
    "risk": "risk_ok",
}


def explain_signal(
    *,
    signal: str,
    structural_confidence: float,
    gate_categories: Optional[Dict[str, bool]] = None,
    block_reasons: Optional[List[str]] = None,
    fsm_state: str = "",
    setup_type: str = "none",
    market_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build human-readable signal explanation persisted at entry."""
    cats = gate_categories or {}
    blocks = list(block_reasons or [])
    reasons: List[str] = []
    rejected: List[str] = []

    for cat, label in _GATE_LABELS.items():
        if cats.get(cat):
            reasons.append(label)
        elif cat in cats:
            rejected.append(label)

    ms = market_state if isinstance(market_state, dict) else {}
    if str(ms.get("momentum") or "") == "increasing":
        reasons.append("momentum_increasing")
    mtf = ms.get("mtf") if isinstance(ms.get("mtf"), dict) else {}
    h1 = str(mtf.get("h1") or "").lower()
    if "bull" in h1:
        reasons.append("h1_bullish")
    elif "bear" in h1:
        reasons.append("h1_bearish")

    for br in blocks[:5]:
        if br not in rejected:
            rejected.append(br)

    conf_pct = round(max(0.0, min(100.0, float(structural_confidence or 0.0) * 100.0)), 1)

    return {
        "signal": str(signal or "HOLD").upper(),
        "confidence_pct": conf_pct,
        "reasons": reasons,
        "rejected_rules": rejected,
        "gate_categories": dict(cats),
        "fsm_state": str(fsm_state or ""),
        "setup_type": str(setup_type or "none"),
    }
