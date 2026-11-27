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


_DIRECTIONAL_SIGNALS = frozenset({"BUY", "SELL", "STRONG_BUY", "STRONG_SELL"})


def _as_zone_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    zones: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        try:
            price = float(item.get("price"))
            low = float(item.get("low"))
            high = float(item.get("high"))
        except (TypeError, ValueError):
            continue
        timeframe = str(item.get("timeframe") or "")
        if not timeframe or price <= 0.0:
            continue
        zones.append(
            {
                "timeframe": timeframe,
                "price": price,
                "low": low,
                "high": high,
            }
        )
    return zones


def _as_pattern_list(value: object) -> list[dict[str, Any]]:
    """Normalize in-house candlestick / chart-pattern hits for the chart API."""
    if not isinstance(value, list):
        return []
    patterns: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        try:
            time_s = int(item.get("time"))
        except (TypeError, ValueError):
            continue
        name = str(item.get("name") or "").strip()
        if time_s <= 0 or not name:
            continue
        direction = str(item.get("direction") or "").lower()
        if direction not in {"bullish", "bearish"}:
            continue
        kind = str(item.get("kind") or "").lower()
        if kind not in {"candlestick", "chart"}:
            kind = "candlestick" if name.startswith("cdl_") else "chart"
        price = None
        raw_price = item.get("price")
        if raw_price is not None:
            try:
                price_f = float(raw_price)
                if price_f > 0.0:
                    price = price_f
            except (TypeError, ValueError):
                price = None
        patterns.append(
            {
                "time": time_s,
                "name": name,
                "label": str(item.get("label") or name),
                "direction": direction,
                "timeframe": str(item.get("timeframe") or ""),
                "kind": kind,
                "price": price,
            }
        )
    return patterns


def _risk_reward(entry: float | None, stop: float | None, take: float | None) -> float | None:
    if entry is None or stop is None or take is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0.0:
        return None
    return abs(take - entry) / risk


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
        ``execution_authorized`` is false. Chart overlays (zones, entry)
        are included for the Market Analysis dashboard.
    """
    signal = str(scored.get("signal") or "HOLD")
    directional = signal in _DIRECTIONAL_SIGNALS
    invalidation = _invalidation_list(scored.get("invalidation"))
    entry = None
    stop = None
    take = None
    if directional:
        raw_entry = scored.get("entry_price", scored.get("close"))
        try:
            entry = float(raw_entry) if raw_entry is not None else None
        except (TypeError, ValueError):
            entry = None
        if entry is not None and entry <= 0.0:
            entry = None
        try:
            stop = float(scored["stop_price"]) if scored.get("stop_price") is not None else None
        except (TypeError, ValueError, KeyError):
            stop = None
        try:
            take = (
                float(scored["take_profit_price"])
                if scored.get("take_profit_price") is not None
                else None
            )
        except (TypeError, ValueError, KeyError):
            take = None
        if stop is not None and stop <= 0.0:
            stop = None
        if take is not None and take <= 0.0:
            take = None
    return {
        "decision_id": decision_id or str(uuid.uuid4()),
        "decision_path": "algorithmic",
        "symbol": symbol,
        "signal": signal,
        "confidence": float(scored.get("confidence") or 0.0),
        "score": float(scored.get("score") or 0.0),
        "candle_timestamp": _stamp(scored.get("decision_time")),
        "market_context": timeframe_context(scored),
        "risk": {
            "stop_loss": stop,
            "take_profit": take,
            "position_size": 0.0,
        },
        "entry": entry,
        "support_zones": _as_zone_list(scored.get("support_zones")),
        "resistance_zones": _as_zone_list(scored.get("resistance_zones")),
        "active_patterns": _as_pattern_list(scored.get("active_patterns")),
        "risk_reward": _risk_reward(entry, stop, take),
        "valid": directional and not invalidation,
        "reasons": list(reasons),
        "invalidation": invalidation,
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
    signal = str(verdict.get("signal") or decision.get("signal") or "HOLD")
    invalidation = _invalidation_list(context.get("invalidation"))
    directional = signal in _DIRECTIONAL_SIGNALS
    entry = plan.get("entry")
    try:
        entry_f = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        entry_f = None
    stop = plan.get("stop_loss")
    take = plan.get("take_profit")
    try:
        stop_f = float(stop) if stop is not None else None
    except (TypeError, ValueError):
        stop_f = None
    try:
        take_f = float(take) if take is not None else None
    except (TypeError, ValueError):
        take_f = None
    return {
        "decision_id": str(reasoning.get("chain_id") or uuid.uuid4()),
        "decision_path": str(context.get("decision_path") or "model"),
        "symbol": str(result.get("symbol") or ""),
        "signal": signal,
        "confidence": float(verdict.get("confidence") or decision.get("confidence") or 0.0),
        "score": context.get("algo_score"),
        "candle_timestamp": context.get("candle_timestamp"),
        "market_context": context.get("timeframes")
        if isinstance(context.get("timeframes"), dict)
        else {"5m": {}, "15m": {}, "1h": {}, "4h": {}},
        "risk": {
            "stop_loss": stop_f,
            "take_profit": take_f,
            "position_size": float(
                verdict.get("position_size") or decision.get("position_size") or 0.0
            ),
        },
        "entry": entry_f,
        "support_zones": _as_zone_list(context.get("support_zones")),
        "resistance_zones": _as_zone_list(context.get("resistance_zones")),
        "active_patterns": _as_pattern_list(context.get("active_patterns")),
        "risk_reward": _risk_reward(entry_f, stop_f, take_f),
        "valid": directional and not invalidation,
        "reasons": [str(item) for item in reasons],
        "invalidation": invalidation,
        "execution_authorized": False,
        "score_breakdown": context.get("algo_components")
        if isinstance(context.get("algo_components"), dict)
        else {},
    }
