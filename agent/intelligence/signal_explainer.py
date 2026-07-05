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
    decision_context_v3: Optional[Dict[str, Any]] = None,
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

    cognition: Dict[str, Any] = {}
    dc = decision_context_v3 if isinstance(decision_context_v3, dict) else {}
    if dc:
        if isinstance(dc.get("scenario"), dict):
            cognition["scenario"] = dc["scenario"].get("primary")
        if isinstance(dc.get("expectation"), dict):
            cognition["dominant_expectation"] = dc["expectation"].get("dominant_expectation")
            horizons = dc["expectation"].get("horizons") or []
            if horizons:
                cognition["expectation_horizons"] = [
                    {
                        "minutes": h.get("horizon_minutes"),
                        "trend_persistence": h.get("trend_persistence"),
                        "breakout_likelihood": h.get("breakout_likelihood"),
                    }
                    for h in horizons[:4]
                    if isinstance(h, dict)
                ]
        if isinstance(dc.get("risk_intelligence"), dict):
            cognition["trade_environment_score"] = dc["risk_intelligence"].get(
                "trade_environment_score"
            )
        if isinstance(dc.get("strategy_scores"), dict):
            entries = dc["strategy_scores"].get("entries") or []
            cognition["strategy_ranking"] = [
                {"profile": e.get("profile_id"), "score": e.get("adjusted_confidence")}
                for e in entries[:5]
                if isinstance(e, dict)
            ]

    out = {
        "signal": str(signal or "HOLD").upper(),
        "confidence_pct": conf_pct,
        "reasons": reasons,
        "rejected_rules": rejected,
        "gate_categories": dict(cats),
        "fsm_state": str(fsm_state or ""),
        "setup_type": str(setup_type or "none"),
    }
    if cognition:
        out["cognition"] = cognition
    return out
