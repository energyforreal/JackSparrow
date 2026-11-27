"""Shared verdict passed from a predictor to the trading agent.

The scorer and any future model path fill this object. Neither path sets
``execution_authorized`` or a position size. The risk manager sizes the trade,
and the execution engine is the only component that may authorize an order.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping


def capped_risk_fraction(configured: float, maximum: float) -> float:
    """Return a position fraction from risk settings, ignoring signal confidence.

    Args:
        configured: Portfolio fraction from risk configuration.
        maximum: Hard cap, also from risk configuration.

    Returns:
        Fraction in ``[0.01, 1]``.
    """
    cap = min(1.0, max(0.01, float(maximum)))
    return max(0.01, min(cap, float(configured)))


def timeframe_context(scored: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Expose component points by timeframe without indicator internals.

    Args:
        scored: Algorithmic score payload.

    Returns:
        One public summary per required timeframe.
    """
    long_score = float(scored.get("long_score") or 0.0)
    short_score = float(scored.get("short_score") or 0.0)
    points = scored.get("long_components") if long_score >= short_score else scored.get(
        "short_components"
    )
    if not isinstance(points, Mapping):
        points = scored.get("components") if isinstance(scored.get("components"), Mapping) else {}
    return {
        "5m": {
            "confirmation": float(points.get("confirm_5m") or 0.0),
            "volume": float(points.get("volume") or 0.0),
            "momentum": float(points.get("momentum") or 0.0),
        },
        "15m": {"pattern": float(points.get("pattern_15m") or 0.0)},
        "1h": {
            "structure": float(points.get("structure_1h") or 0.0),
            "zone": float(points.get("zone_rejection") or 0.0),
        },
        "4h": {"trend": float(points.get("trend_4h") or 0.0)},
    }


def _stamp(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _invalidation_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = str(value or "")
    if not text or text == "below_threshold":
        return []
    return [text]


def build_algorithmic_decision(
    *,
    symbol: str,
    scored: Mapping[str, Any],
    reasons: list[str],
    decision_id: str | None = None,
) -> dict[str, Any]:
    """Build the shared decision object for one algorithmic score.

    Args:
        symbol: Instrument.
        scored: Score payload. Its confidence is the normalized score.
        reasons: Stable reason codes.
        decision_id: Optional id. A new id is created when omitted.

    Returns:
        Decision object. ``risk.position_size`` is zero and
        ``execution_authorized`` is false.
    """
    return {
        "decision_id": decision_id or str(uuid.uuid4()),
        "decision_path": "algorithmic",
        "symbol": symbol,
        "signal": str(scored.get("signal") or "HOLD"),
        "confidence": float(scored.get("confidence") or 0.0),
        "score": float(scored.get("score") or 0.0),
        "candle_timestamp": _stamp(scored.get("decision_time")),
        "market_context": timeframe_context(scored),
        "risk": {
            "stop_loss": scored.get("stop_price"),
            "take_profit": scored.get("take_profit_price"),
            "position_size": 0.0,
        },
        "reasons": list(reasons),
        "invalidation": _invalidation_list(scored.get("invalidation")),
        "execution_authorized": False,
        "score_breakdown": dict(scored.get("components") or {}),
    }


def ensure_trading_decision(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the shared decision on a prediction result.

    Algorithmic results already carry one. Model results are wrapped without
    changing their signal, confidence, or size.

    Args:
        result: Orchestrator prediction payload.

    Returns:
        Shared decision object. Execution remains unauthorized.
    """
    existing = result.get("trading_decision")
    if isinstance(existing, dict) and existing.get("decision_path"):
        return dict(existing)
    verdict = result.get("policy_verdict") if isinstance(result.get("policy_verdict"), dict) else {}
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    context = result.get("market_context") if isinstance(result.get("market_context"), dict) else {}
    reasoning = result.get("reasoning") if isinstance(result.get("reasoning"), dict) else {}
    plan = context.get("execution_plan") if isinstance(context.get("execution_plan"), dict) else {}
    reasons = verdict.get("reason_codes") or decision.get("policy_reason_codes") or []
    return {
        "decision_id": str(reasoning.get("chain_id") or uuid.uuid4()),
        "decision_path": str(context.get("decision_path") or "model"),
        "symbol": str(result.get("symbol") or ""),
        "signal": str(verdict.get("signal") or decision.get("signal") or "HOLD"),
        "confidence": float(verdict.get("confidence") or decision.get("confidence") or 0.0),
        "score": context.get("algo_score"),
        "candle_timestamp": context.get("candle_timestamp"),
        "market_context": context.get("timeframes")
        if isinstance(context.get("timeframes"), dict)
        else {"5m": {}, "15m": {}, "1h": {}, "4h": {}},
        "risk": {
            "stop_loss": plan.get("stop_loss"),
            "take_profit": plan.get("take_profit"),
            "position_size": float(
                verdict.get("position_size") or decision.get("position_size") or 0.0
            ),
        },
        "reasons": [str(item) for item in reasons],
        "invalidation": _invalidation_list(context.get("invalidation")),
        "execution_authorized": False,
        "score_breakdown": context.get("algo_components")
        if isinstance(context.get("algo_components"), dict)
        else {},
    }
