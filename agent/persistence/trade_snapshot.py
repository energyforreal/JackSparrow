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

_TRUNCATABLE_KEYS = ("narrative_tail", "features", "confluence_components")


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
    reflection = close_payload.get("reflection_snapshot")
    if isinstance(reflection, dict):
        outcome["reflection_snapshot"] = reflection
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
    merged["execution_timing"] = timing

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
    return trimmed
