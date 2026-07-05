"""Four-dimension post-trade quality assessment."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.core.config import settings


def _quality_entry(dc: Dict[str, Any], outcome: Dict[str, Any]) -> str:
    mv = dc.get("market_validation") if isinstance(dc.get("market_validation"), dict) else {}
    score = float(mv.get("validation_score") or 0.0)
    pnl = float(outcome.get("pnl_usd") or 0.0)
    if score >= 75 and pnl > 0:
        return "excellent"
    if score >= 60:
        return "adequate"
    return "poor"


def _quality_execution(timing: Dict[str, Any], outcome: Dict[str, Any]) -> str:
    risk_to_fill = timing.get("risk_to_fill_ms")
    if risk_to_fill is not None:
        try:
            if float(risk_to_fill) > 5000:
                return "poor"
            if float(risk_to_fill) > 2000:
                return "adequate"
        except (TypeError, ValueError):
            pass
    fees = float(outcome.get("fees_usd") or 0.0)
    gross = float(outcome.get("gross_pnl_usd") or 0.0)
    if gross > 0 and fees >= gross:
        return "poor"
    return "adequate"


def _quality_exit(
    outcome: Dict[str, Any],
    monitoring: List[Dict[str, Any]],
    timeline: List[str],
) -> str:
    reason = str(outcome.get("exit_reason") or "")
    pnl = float(outcome.get("pnl_usd") or 0.0)
    if reason == "take_profit_hit" and pnl > 0:
        return "optimal"
    if reason == "lifecycle_exit" and monitoring:
        last_opp = monitoring[-1].get("opportunity_score")
        try:
            if last_opp is not None and float(last_opp) >= 80 and pnl > 0:
                return "too_early"
        except (TypeError, ValueError):
            pass
    if timeline and len(timeline) >= 2:
        if timeline[-1] in ("bearish", "weak_bearish") and timeline[0] in ("bullish", "weak_bullish"):
            if pnl > 0:
                return "optimal"
            return "too_late"
    if pnl < 0 and reason in ("stop_loss_hit", "lifecycle_exit"):
        return "adequate"
    return "adequate"


def _market_conditions(timeline: List[str], dc: Dict[str, Any]) -> str:
    mv = dc.get("market_validation") if isinstance(dc.get("market_validation"), dict) else {}
    benchmark = str(mv.get("regime_benchmark") or "")
    if benchmark in ("trending_strong", "breakout"):
        return "favorable"
    if benchmark in ("ranging", "low_volatility"):
        return "neutral"
    if benchmark in ("volatile", "reversal"):
        return "adverse"
    if timeline and timeline[-1] in ("bullish", "bearish"):
        return "favorable"
    return "neutral"


def _derive_strategy_quality(
    entry_q: str,
    exit_q: str,
    market_q: str,
    pnl: float,
) -> str:
    if entry_q in ("excellent", "adequate") and market_q == "favorable" and pnl > 0:
        return "effective"
    if entry_q == "poor" or market_q == "adverse":
        return "ineffective"
    if exit_q == "too_early" and pnl > 0:
        return "effective"
    return "mixed"


def _root_cause(
    entry_q: str,
    exit_q: str,
    exec_q: str,
    market_q: str,
    outcome: Dict[str, Any],
    wallet_attr: Optional[Dict[str, Any]] = None,
) -> str:
    pnl = float(outcome.get("pnl_usd") or 0.0)
    fees = float(outcome.get("fees_usd") or 0.0)
    gross = float(outcome.get("gross_pnl_usd") or 0.0)
    wa = wallet_attr if isinstance(wallet_attr, dict) else {}
    funding_usd = float(wa.get("funding_usd") or 0.0)
    net_wallet = float(wa.get("net_wallet_impact_usd") or 0.0)
    use_wallet = bool(wa) and abs(funding_usd) + abs(net_wallet) > 0

    if use_wallet and gross != 0 and abs(funding_usd) > abs(gross):
        return "funding_dominated"
    if use_wallet and gross > 0 and net_wallet < 0:
        return "cost_drag"
    if gross > 0 and pnl < 0 and fees >= gross:
        return "fee_dominated"
    if entry_q == "poor":
        return "poor_entry"
    if exit_q == "too_early":
        return "early_exit"
    if exit_q == "too_late":
        return "late_exit"
    if market_q == "adverse":
        return "wrong_trend"
    if exec_q == "poor":
        return "execution_delay"
    if str(outcome.get("exit_reason") or "") == "lifecycle_exit" and pnl < 0:
        return "risk_management"
    return "unknown"


def analyze_post_trade(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Produce four-dimension post-trade assessment from close snapshot."""
    dc = snapshot.get("decision_context") if isinstance(snapshot.get("decision_context"), dict) else {}
    outcome = snapshot.get("outcome") if isinstance(snapshot.get("outcome"), dict) else {}
    timing = snapshot.get("execution_timing") if isinstance(snapshot.get("execution_timing"), dict) else {}
    monitoring = snapshot.get("position_monitoring")
    if not isinstance(monitoring, list):
        monitoring = []
    timeline = snapshot.get("market_structure_timeline")
    if not isinstance(timeline, list):
        timeline = []

    pnl = float(outcome.get("pnl_usd") or 0.0)
    entry_q = _quality_entry(dc, outcome)
    exec_q = _quality_execution(timing, outcome)
    exit_q = _quality_exit(outcome, monitoring, timeline)
    market_q = _market_conditions(timeline, dc)
    strategy_q = _derive_strategy_quality(entry_q, exit_q, market_q, pnl)
    wallet_attr = snapshot.get("wallet_attribution")
    if not isinstance(wallet_attr, dict):
        wallet_attr = outcome.get("wallet_attribution")
    if not isinstance(wallet_attr, dict):
        wallet_attr = None
    use_wallet_learning = bool(
        getattr(settings, "wallet_attribution_in_learning_enabled", False)
    )
    root = _root_cause(
        entry_q,
        exit_q,
        exec_q,
        market_q,
        outcome,
        wallet_attr if use_wallet_learning else None,
    )

    recommendations: List[str] = []
    if root == "poor_entry":
        recommendations.append("increase_trend_requirement")
    if root == "early_exit":
        recommendations.append("increase_lifecycle_threshold")
    if root == "fee_dominated":
        recommendations.append("increase_position_size_or_reduce_frequency")
    if root == "funding_dominated":
        recommendations.append("reduce_hold_duration_or_avoid_negative_funding")
    if root == "cost_drag":
        recommendations.append("review_wallet_costs_vs_gross_edge")
    if root == "wrong_trend":
        recommendations.append("tighten_regime_filter")

    v3 = dc.get("decision_context_v3") if isinstance(dc.get("decision_context_v3"), dict) else {}
    cognition_tags: Dict[str, Any] = {}
    if v3:
        if isinstance(v3.get("scenario"), dict):
            cognition_tags["scenario_at_entry"] = v3["scenario"].get("primary")
        if isinstance(v3.get("expectation"), dict):
            cognition_tags["expectation_at_entry"] = v3["expectation"].get("dominant_expectation")
        if isinstance(v3.get("risk_intelligence"), dict):
            cognition_tags["risk_at_entry"] = v3["risk_intelligence"].get("trade_environment_score")
        scores = v3.get("strategy_scores")
        if isinstance(scores, dict):
            entries = scores.get("entries") or []
            if entries and isinstance(entries[0], dict):
                best = max(
                    entries,
                    key=lambda e: float(e.get("adjusted_confidence") or 0.0),
                )
                cognition_tags["selected_profile"] = best.get("profile_id")

    result = {
        "entry_quality": entry_q,
        "execution_quality": exec_q,
        "exit_quality": exit_q,
        "market_conditions": market_q,
        "strategy_quality": strategy_q,
        "root_cause": root,
        "recommendation": recommendations[0] if recommendations else "continue_monitoring",
        "recommendations": recommendations,
        "confidence": 0.75 if root != "unknown" else 0.5,
    }
    if cognition_tags:
        result["cognition_tags"] = cognition_tags
    return result
