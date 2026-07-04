"""Trade decision snapshot builders for historical optimization analytics."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.core.config import settings
from agent.core.gate_profile import gate_profile
from agent.core.logging_utils import get_session_id
from agent.intelligence.logic_version import get_logic_version

DEFAULT_FEATURE_KEYS: tuple[str, ...] = (
    "atr_14",
    "rsi_14",
    "adx_14",
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_200",
    "volume_zscore",
    "vwap_distance",
    "funding_rate",
    "open_interest",
    "spread_bps",
    "close",
    "high",
    "low",
    "volume",
)

_TRUNCATABLE_KEYS = ("narrative_tail", "features", "confluence_components", "position_monitoring")


def _copy_dict_if_present(src: Any) -> Optional[Dict[str, Any]]:
    if isinstance(src, dict) and src:
        return dict(src)
    return None


def _policy_verdict_subset(pv: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(pv, dict):
        return None
    out: Dict[str, Any] = {}
    for key in (
        "signal",
        "confidence",
        "conviction",
        "reason_codes",
        "abstention",
        "ml_evidence_id",
        "adopted_ml_candidate",
        "evidence",
    ):
        if pv.get(key) is not None:
            out[key] = pv.get(key)
    return out or None


def _thesis_verdict_subset(tv: Any) -> Optional[Dict[str, Any]]:
    if tv is None:
        return None
    if hasattr(tv, "to_dict"):
        try:
            raw = tv.to_dict()
            return dict(raw) if isinstance(raw, dict) else None
        except Exception:
            pass
    if isinstance(tv, dict):
        return dict(tv)
    return None


def _enrich_decision_context_v2(
    decision_context: Dict[str, Any],
    *,
    risk_payload: Dict[str, Any],
    market_context: Dict[str, Any],
) -> None:
    """Attach v2 learning fields from risk payload and market context."""
    mc = market_context if isinstance(market_context, dict) else {}
    eq = mc.get("entry_quality")
    if not isinstance(eq, dict):
        eq = risk_payload.get("entry_quality")
    if isinstance(eq, dict):
        decision_context["entry_quality"] = dict(eq)

    hyp = mc.get("hypothesis_snapshot")
    if isinstance(hyp, dict):
        decision_context["hypothesis_snapshot"] = dict(hyp)

    pv = _policy_verdict_subset(risk_payload.get("policy_verdict"))
    if pv:
        decision_context["policy_verdict"] = pv
        if decision_context.get("conviction_at_entry") is None and pv.get("conviction") is not None:
            decision_context["conviction_at_entry"] = pv.get("conviction")

    tv = _thesis_verdict_subset(mc.get("thesis_verdict"))
    if tv:
        decision_context["thesis_verdict"] = tv


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build_system_context() -> Dict[str, Any]:
    """Stable config fingerprint for cohort analysis (no secrets)."""
    cfg: Dict[str, Any] = {
        "decision_engine_mode": str(
            getattr(settings, "decision_engine_mode", "ml_legacy") or "ml_legacy"
        ),
        "gate_profile": gate_profile(),
        "trading_mode": str(getattr(settings, "trading_mode", "testnet") or "testnet"),
        "trading_symbol": str(
            getattr(settings, "trading_symbol", None)
            or getattr(settings, "symbol", "BTCUSD")
            or "BTCUSD"
        ),
        "stop_loss_percentage": float(getattr(settings, "stop_loss_percentage", 0.02) or 0.02),
        "take_profit_percentage": float(
            getattr(settings, "take_profit_percentage", 0.04) or 0.04
        ),
        "use_atr_scaled_sl_tp": bool(getattr(settings, "use_atr_scaled_sl_tp", False)),
        "max_drawdown": float(getattr(settings, "max_drawdown", 0.15) or 0.15),
        "agent_daily_drawdown_halt_pct": float(
            getattr(settings, "agent_daily_drawdown_halt_pct", 5.0) or 5.0
        ),
        "structural_gate_min_trend_age": int(
            getattr(settings, "structural_gate_min_trend_age", 3) or 3
        ),
        "structural_gate_max_failed_breakouts": int(
            getattr(settings, "structural_gate_max_failed_breakouts", 2) or 2
        ),
    }
    digest = hashlib.sha256(_canonical_json(cfg).encode("utf-8")).hexdigest()[:8]
    ctx: Dict[str, Any] = dict(cfg)
    ctx["config_hash"] = digest
    ctx["session_id"] = get_session_id()
    build_id = os.environ.get("BUILD_ID") or os.environ.get("GIT_COMMIT")
    if build_id:
        ctx["build_id"] = str(build_id).strip()[:64]
    ctx["logic_version"] = get_logic_version()
    return ctx


def _feature_allowlist() -> List[str]:
    raw = getattr(settings, "trade_snapshot_feature_keys", None)
    if isinstance(raw, str) and raw.strip():
        return [k.strip() for k in raw.split(",") if k.strip()]
    if isinstance(raw, (list, tuple)) and raw:
        return [str(k) for k in raw]
    return list(DEFAULT_FEATURE_KEYS)


def _pick_features(features: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(features, dict):
        return {}
    allow = _feature_allowlist()
    out: Dict[str, Any] = {}
    for key in allow:
        if key not in features:
            continue
        val = features[key]
        if val is None:
            continue
        try:
            fv = float(val)
            if fv == fv:  # finite
                out[key] = fv
        except (TypeError, ValueError):
            if isinstance(val, (str, bool, int)):
                out[key] = val
    return out


def _extract_gate_evaluation(rb: Dict[str, Any]) -> Dict[str, Any]:
    gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
    return {
        "trade_allowed": bool(gates.get("trade_allowed", False)),
        "categories": dict(gates.get("categories") or {}),
        "block_reasons": list(gates.get("block_reasons") or []),
        "setup_type": str(gates.get("setup_type") or "none"),
        "structural_confidence": rb.get("structural_confidence"),
    }


def _rule_based_subset(market_context: Dict[str, Any]) -> Dict[str, Any]:
    rb = market_context.get("rule_based_pipeline")
    if not isinstance(rb, dict):
        rb = {}
    narrative = rb.get("narrative_tail")
    if isinstance(narrative, list):
        narrative = narrative[-5:]
    else:
        narrative = []
    out: Dict[str, Any] = {}
    for key in ("market_state", "structural_gates", "fsm_decision"):
        val = rb.get(key)
        if isinstance(val, dict):
            out[key] = dict(val)
    out["narrative_tail"] = narrative
    if rb.get("structural_confidence") is not None:
        out["structural_confidence"] = rb.get("structural_confidence")
    return out


def reconstruct_market_context_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild market_context for archetype hooks from stored entry snapshot."""
    dc = snapshot.get("decision_context")
    if not isinstance(dc, dict):
        return {}
    rb = dc.get("rule_based_pipeline")
    if not isinstance(rb, dict):
        rb = {}
    mc: Dict[str, Any] = {"rule_based_pipeline": rb}
    features = dc.get("features")
    if isinstance(features, dict):
        mc["features"] = dict(features)
    narrative = rb.get("narrative_tail")
    if isinstance(narrative, list):
        mc["narrative_tail"] = list(narrative)
    return mc


def build_entry_snapshot(
    *,
    risk_payload: Dict[str, Any],
    reasoning_chain: Optional[Dict[str, Any]] = None,
    timing_ctx: Optional[Dict[str, Any]] = None,
    performance_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build versioned entry snapshot from risk-approved payload."""
    if not getattr(settings, "trade_entry_snapshot_enabled", True):
        return {}

    rc = reasoning_chain if isinstance(reasoning_chain, dict) else {}
    mc = risk_payload.get("market_context")
    if not isinstance(mc, dict):
        mc = rc.get("market_context") if isinstance(rc.get("market_context"), dict) else {}

    rb_subset = _rule_based_subset(mc)
    features_src = mc.get("features") if isinstance(mc.get("features"), dict) else {}
    if not features_src and isinstance(rc.get("market_context"), dict):
        fs = rc["market_context"].get("features")
        if isinstance(fs, dict):
            features_src = fs

    reasoning_chain_id = (
        risk_payload.get("reasoning_chain_id")
        or rc.get("chain_id")
        or risk_payload.get("decision_event_id")
    )

    decision_context: Dict[str, Any] = {
        "reasoning_chain_id": reasoning_chain_id,
        "symbol": str(risk_payload.get("symbol") or mc.get("symbol") or ""),
        "signal": str(risk_payload.get("side") or risk_payload.get("signal") or ""),
        "side": str(risk_payload.get("side") or ""),
        "confidence": risk_payload.get("confidence"),
        "structural_confidence": rb_subset.get("structural_confidence"),
        "rule_based_pipeline": rb_subset,
        "gate_evaluation": _extract_gate_evaluation(rb_subset),
        "features": _pick_features(features_src),
        "stop_loss": risk_payload.get("stop_loss"),
        "take_profit": risk_payload.get("take_profit"),
        "atr_14": risk_payload.get("atr_14"),
        "leverage": risk_payload.get("leverage"),
        "entry_lots": risk_payload.get("entry_lots"),
    }

    pv = risk_payload.get("policy_verdict")
    if isinstance(pv, dict) and pv.get("conviction") is not None:
        decision_context["conviction_at_entry"] = pv.get("conviction")
    elif risk_payload.get("conviction") is not None:
        decision_context["conviction_at_entry"] = risk_payload.get("conviction")

    ml_ev = risk_payload.get("ml_evidence_snapshot")
    if isinstance(ml_ev, dict):
        decision_context["evidence_at_entry"] = {
            k: ml_ev.get(k)
            for k in ("trade_score", "thesis_signal", "model_confidence", "consensus_confidence")
            if ml_ev.get(k) is not None
        }
    if risk_payload.get("take_profit") is not None:
        decision_context["take_profit_at_entry"] = risk_payload.get("take_profit")
    if risk_payload.get("stop_loss") is not None:
        decision_context["stop_loss_at_entry"] = risk_payload.get("stop_loss")

    diag = risk_payload.get("signal_path_diagnostics")
    if isinstance(diag, dict):
        decision_context["signal_path_diagnostics"] = dict(diag)
    intro = risk_payload.get("agent_introspection_at_entry")
    if isinstance(intro, dict):
        decision_context["agent_introspection_at_entry"] = dict(intro)

    trade_score = mc.get("trade_score")
    if isinstance(trade_score, dict) and trade_score.get("components"):
        decision_context["confluence_components"] = dict(trade_score.get("components") or {})
    elif isinstance(mc.get("environment_scores"), dict):
        decision_context["confluence_components"] = dict(mc["environment_scores"])

    rb_full = mc.get("rule_based_pipeline") if isinstance(mc.get("rule_based_pipeline"), dict) else {}
    if rb_full.get("market_validation"):
        decision_context["market_validation"] = dict(rb_full["market_validation"])
    if rb_full.get("signal_explanation"):
        decision_context["signal_explanation"] = dict(rb_full["signal_explanation"])
    ms_rb = rb_subset.get("market_state") if isinstance(rb_subset.get("market_state"), dict) else {}
    if ms_rb.get("regime_benchmark"):
        decision_context["regime_benchmark"] = ms_rb.get("regime_benchmark")

    _enrich_decision_context_v2(
        decision_context,
        risk_payload=risk_payload,
        market_context=mc,
    )

    snap: Dict[str, Any] = {
        "snapshot_version": int(getattr(settings, "trade_snapshot_version", 1) or 1),
        "captured_at": _iso_now(),
        "snapshot_kind": "entry",
        "system_context": build_system_context(),
        "decision_context": decision_context,
    }

    if timing_ctx and isinstance(timing_ctx, dict):
        snap["execution_timing"] = dict(timing_ctx)

    include_perf = getattr(settings, "trade_snapshot_include_performance_context", True)
    if include_perf and performance_ctx and isinstance(performance_ctx, dict):
        snap["performance_context"] = dict(performance_ctx)

    return enforce_snapshot_size_cap(snap)


def build_entry_state_summary(
    entry_snapshot: Dict[str, Any],
    position: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalized entry fields for analytics without deep JSON traversal."""
    dc = (
        entry_snapshot.get("decision_context")
        if isinstance(entry_snapshot.get("decision_context"), dict)
        else entry_snapshot
    )
    if not isinstance(dc, dict):
        dc = {}
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    mstate = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    fsm = rb.get("fsm_decision") if isinstance(rb.get("fsm_decision"), dict) else {}
    pos = position or {}
    summary: Dict[str, Any] = {
        "confidence": dc.get("confidence"),
        "conviction": dc.get("conviction_at_entry") or pos.get("conviction_at_entry"),
        "regime": mstate.get("regime") or dc.get("regime"),
        "signal": dc.get("signal") or dc.get("side"),
        "fsm_thesis_health": fsm.get("thesis_health"),
        "structural_confidence": rb.get("structural_confidence"),
        "entry_lots": dc.get("entry_lots") or pos.get("lots") or pos.get("quantity"),
        "stop_loss_at_entry": dc.get("stop_loss_at_entry") or pos.get("stop_loss_at_entry"),
        "take_profit_at_entry": dc.get("take_profit_at_entry") or pos.get("take_profit_at_entry"),
    }
    return {k: v for k, v in summary.items() if v is not None}


def merge_close_fields(
    entry_snapshot: Dict[str, Any],
    close_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge entry snapshot with close outcome for trade_outcomes.metadata."""
    merged = json.loads(json.dumps(entry_snapshot or {}, default=str))
    merged["snapshot_kind"] = "closed_round_trip"
    merged["closed_at"] = (
        close_payload.get("timestamp").isoformat()
        if hasattr(close_payload.get("timestamp"), "isoformat")
        else close_payload.get("timestamp")
    )

    outcome: Dict[str, Any] = {
        "position_id": close_payload.get("position_id"),
        "exit_price": close_payload.get("exit_price"),
        "entry_price": close_payload.get("entry_price"),
        "pnl_usd": close_payload.get("pnl") or close_payload.get("pnl_usd"),
        "gross_pnl_usd": close_payload.get("gross_pnl_usd"),
        "fees_usd": close_payload.get("fees_usd"),
        "exit_reason": close_payload.get("exit_reason"),
        "duration_seconds": close_payload.get("duration_seconds"),
        "quantity": close_payload.get("quantity"),
        "side": close_payload.get("side"),
    }
    for key in (
        "reference_price_entry",
        "fill_price_entry",
        "reference_price_exit",
        "fill_price_exit",
    ):
        if close_payload.get(key) is not None:
            outcome[key] = close_payload.get(key)
    tp_sl_hist = close_payload.get("tp_sl_history")
    if isinstance(tp_sl_hist, list) and tp_sl_hist:
        outcome["tp_sl_history"] = tp_sl_hist[-100:]
    excursions = close_payload.get("excursions")
    if isinstance(excursions, dict):
        outcome["excursions"] = dict(excursions)
    reflection = close_payload.get("reflection_snapshot")
    if isinstance(reflection, dict):
        outcome["reflection_snapshot"] = reflection
    lifecycle_exit = close_payload.get("lifecycle_exit")
    if isinstance(lifecycle_exit, dict):
        outcome["lifecycle_exit"] = lifecycle_exit
    entry_summary = close_payload.get("entry_state_summary")
    if isinstance(entry_summary, dict):
        merged["entry_state_summary"] = entry_summary
    elif entry_snapshot:
        merged["entry_state_summary"] = build_entry_state_summary(entry_snapshot)
    merged["outcome"] = outcome

    timing = merged.get("execution_timing")
    if not isinstance(timing, dict):
        timing = {}
    close_ts = close_payload.get("timestamp")
    if close_ts is not None:
        timing["position_closed_at"] = (
            close_ts.isoformat() if hasattr(close_ts, "isoformat") else str(close_ts)
        )
    risk_at = timing.get("risk_approved_at")
    fill_at = timing.get("exchange_filled_at") or timing.get("position_opened_at")
    if risk_at and fill_at:
        try:
            t_risk = datetime.fromisoformat(str(risk_at).replace("Z", "+00:00"))
            t_fill = datetime.fromisoformat(str(fill_at).replace("Z", "+00:00"))
            timing["risk_to_fill_ms"] = (t_fill - t_risk).total_seconds() * 1000.0
        except (ValueError, TypeError):
            pass
    decision_at = timing.get("decision_created_at")
    if decision_at and risk_at:
        try:
            t_dec = datetime.fromisoformat(str(decision_at).replace("Z", "+00:00"))
            t_risk = datetime.fromisoformat(str(risk_at).replace("Z", "+00:00"))
            timing["decision_to_risk_ms"] = (t_risk - t_dec).total_seconds() * 1000.0
        except (ValueError, TypeError):
            pass
    for slip_key in (
        "execution_slippage_bps_entry",
        "execution_slippage_bps_exit",
        "reference_price_entry",
        "fill_price_entry",
        "reference_price_exit",
        "fill_price_exit",
    ):
        if close_payload.get(slip_key) is not None:
            timing[slip_key] = close_payload.get(slip_key)
    merged["execution_timing"] = timing

    monitoring = close_payload.get("position_monitoring")
    if isinstance(monitoring, list) and monitoring:
        max_mon = int(getattr(settings, "trade_snapshot_monitoring_summary_cycles", 10) or 10)
        merged["position_monitoring"] = monitoring[-max_mon:]
        if len(monitoring) > max_mon:
            merged["position_monitoring_total_cycles"] = len(monitoring)
    timeline = close_payload.get("market_structure_timeline")
    if isinstance(timeline, list) and timeline:
        merged["market_structure_timeline"] = timeline

    post_assessment = close_payload.get("post_trade_assessment")
    if isinstance(post_assessment, dict):
        merged["post_trade_assessment"] = post_assessment
    else:
        try:
            from agent.intelligence.post_trade_analyzer import analyze_post_trade

            merged["post_trade_assessment"] = analyze_post_trade(merged)
        except Exception:
            pass

    return enforce_snapshot_size_cap(merged)


def extract_ledger_summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Denormalized fields for agent closed-trade ledger rows."""
    dc = snapshot.get("decision_context") if isinstance(snapshot.get("decision_context"), dict) else {}
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
    mstate = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    fsm = rb.get("fsm_decision") if isinstance(rb.get("fsm_decision"), dict) else {}
    sys_ctx = snapshot.get("system_context") if isinstance(snapshot.get("system_context"), dict) else {}
    return {
        "snapshot_version": snapshot.get("snapshot_version"),
        "config_hash": sys_ctx.get("config_hash"),
        "reasoning_chain_id": dc.get("reasoning_chain_id"),
        "setup_type": gates.get("setup_type"),
        "regime": mstate.get("regime"),
        "gate_categories": dict(gates.get("categories") or {}),
        "fsm_state": fsm.get("fsm_state"),
    }


def build_reject_snapshot(
    *,
    symbol: str,
    signal: Optional[str],
    event_id: str,
    reject_reason: str,
    diagnostics: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Partial snapshot for rejected entry decisions."""
    mc = market_context if isinstance(market_context, dict) else {}
    rb_subset = _rule_based_subset(mc)
    snap: Dict[str, Any] = {
        "snapshot_version": int(getattr(settings, "trade_snapshot_version", 1) or 1),
        "captured_at": _iso_now(),
        "snapshot_kind": "reject",
        "system_context": build_system_context(),
        "decision_context": {
            "symbol": symbol,
            "signal": signal,
            "reject_reason": reject_reason,
            "event_id": event_id,
            "gate_evaluation": _extract_gate_evaluation(rb_subset),
            "rule_based_pipeline": rb_subset,
        },
    }
    if diagnostics:
        snap["diagnostics"] = {
            k: v
            for k, v in diagnostics.items()
            if k not in ("symbol", "signal", "event_id", "reason")
        }
    dc = snap.get("decision_context")
    if isinstance(dc, dict) and isinstance(mc, dict):
        _enrich_decision_context_v2(dc, risk_payload={}, market_context=mc)
    return enforce_snapshot_size_cap(snap)


def enforce_snapshot_size_cap(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Truncate large nested fields to stay under byte budget."""
    max_bytes = int(getattr(settings, "trade_snapshot_max_bytes", 32768) or 32768)
    encoded = _canonical_json(snapshot).encode("utf-8")
    if len(encoded) <= max_bytes:
        return snapshot

    trimmed = json.loads(json.dumps(snapshot, default=str))
    dc = trimmed.get("decision_context")
    if isinstance(dc, dict):
        for key in _TRUNCATABLE_KEYS:
            if key in dc and isinstance(dc[key], (dict, list)):
                dc[key] = {} if isinstance(dc[key], dict) else []
        rb = dc.get("rule_based_pipeline")
        if isinstance(rb, dict) and "narrative_tail" in rb:
            rb["narrative_tail"] = []

    if len(_canonical_json(trimmed).encode("utf-8")) > max_bytes:
        trimmed["_truncated"] = True
        mon = trimmed.get("position_monitoring")
        if isinstance(mon, list) and len(mon) > 50:
            trimmed["position_monitoring"] = mon[-50:]
    return trimmed
