"""Display-only decision metrics for dashboard WebSocket consumers (not entry gates)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.core.confidence_dynamics import aggregate_entry_proba_strength
from agent.core.signal_vocabulary import is_short_signal, normalize_signal


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _economic_edge_from_ml_validation(
    ml_val: Dict[str, Any],
    signal: str,
) -> Optional[float]:
    er = _opt_float(ml_val.get("expected_return"))
    if er is None:
        return None
    sig = normalize_signal(signal or "HOLD")
    if is_short_signal(sig):
        thr = _opt_float(ml_val.get("short_threshold")) or _opt_float(ml_val.get("threshold"))
        if thr is None:
            return None
        return -(er) - thr
    thr = _opt_float(ml_val.get("threshold"))
    if thr is None:
        return None
    return er - thr


def _trade_score_detail_dict(
    payload: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    detail = payload.get("trade_score_detail")
    if isinstance(detail, dict) and detail.get("score") is not None:
        return detail
    ts = payload.get("trade_score")
    if isinstance(ts, dict) and ts.get("score") is not None:
        return ts
    mc = market_context if isinstance(market_context, dict) else {}
    ts_mc = mc.get("trade_score")
    if isinstance(ts_mc, dict) and ts_mc.get("score") is not None:
        return ts_mc
    if ts is not None:
        try:
            return {"score": float(ts), "passed": None, "components": {}, "reason_codes": []}
        except (TypeError, ValueError):
            pass
    return None


def build_display_metrics(
    *,
    signal: str,
    policy_confidence: float,
    reasoning_chain: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    model_predictions: Optional[List[Dict[str, Any]]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute orthogonal dashboard fields; must not affect trading gates."""
    out: Dict[str, Any] = {}
    pl = payload if isinstance(payload, dict) else {}
    rc = reasoning_chain if isinstance(reasoning_chain, dict) else {}
    mc = market_context if isinstance(market_context, dict) else {}
    if not mc and isinstance(rc.get("market_context"), dict):
        mc = rc["market_context"]

    preds = model_predictions
    if preds is None:
        preds = rc.get("model_predictions")
    if not isinstance(preds, list):
        preds = mc.get("model_predictions") if isinstance(mc.get("model_predictions"), list) else []

    ml_val = mc.get("ml_validation") if isinstance(mc.get("ml_validation"), dict) else {}
    edge = _economic_edge_from_ml_validation(ml_val, signal) if ml_val else None
    if edge is None and pl.get("expected_return") is not None and pl.get("threshold") is not None:
        try:
            er = float(pl["expected_return"])
            thr = float(pl["threshold"])
            sig = normalize_signal(signal or "HOLD")
            edge = (-(er) - thr) if is_short_signal(sig) else (er - thr)
        except (TypeError, ValueError):
            edge = None
    if edge is not None:
        out["economic_edge"] = round(edge, 8)

    margin_mean: Optional[float] = None
    if isinstance(rc.get("entry_proba_margin_mean"), (int, float)):
        margin_mean = float(rc["entry_proba_margin_mean"])
    elif preds:
        bundle = aggregate_entry_proba_strength(preds)
        raw_margin = bundle.get("entry_proba_margin_mean")
        if raw_margin is not None:
            margin_mean = float(raw_margin)
    if margin_mean is not None:
        out["entry_proba_margin"] = round(max(0.0, min(1.0, margin_mean)), 6)

    raw_rc = rc.get("reasoning_confidence_raw")
    if raw_rc is not None:
        try:
            out["reasoning_confidence_raw"] = max(0.0, min(1.0, float(raw_rc)))
        except (TypeError, ValueError):
            pass

    ts_detail = _trade_score_detail_dict(pl, mc)
    if ts_detail is not None:
        out["trade_score_detail"] = ts_detail

    chain_final = _opt_float(rc.get("final_confidence"))
    policy = max(0.0, min(1.0, float(policy_confidence or 0.0)))
    if chain_final is not None:
        chain_final = max(0.0, min(1.0, chain_final))
        delta = chain_final - policy
        out["metric_correlation_hint"] = {
            "policy_reasoning_delta": round(delta, 6),
            "policy_confidence": round(policy, 6),
            "reasoning_confidence": round(chain_final, 6),
        }
        if raw_rc is not None:
            try:
                raw_f = float(raw_rc)
                out["metric_correlation_hint"]["reasoning_raw_delta"] = round(
                    chain_final - max(0.0, min(1.0, raw_f)), 6
                )
            except (TypeError, ValueError):
                pass

    return out
