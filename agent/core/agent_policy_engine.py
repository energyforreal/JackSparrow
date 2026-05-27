"""
Agent policy engine — sole authority for autonomous trade intent on the event bus.

ML outputs are packaged as :class:`MLEvidenceSnapshot` (schemas); this module
produces a :class:`PolicyVerdict` that may adopt, veto, or fuse ML with rule-based thesis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.events.schemas import MLEvidenceSnapshot, PolicyVerdict
from agent.core.reasoning_engine import MCPReasoningChain
from agent.core.config import settings
from agent.core.agent_thesis_engine import AgentThesisEngine, ThesisVerdict, agent_thesis_engine
from agent.core.multi_horizon_evidence import (
    MultiHorizonMLEvidence,
    build_multi_horizon_evidence,
    validate_thesis_against_multi_horizon,
)
from feature_store.jacksparrow_v43_horizon import resolve_training_forward_bars

logger = structlog.get_logger()

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_POLICY_MODES = frozenset(
    {"ml_only", "thesis_only", "ml_or_thesis", "ml_and_thesis", "thesis_veto_ml"}
)


def conclusion_to_ml_signal_and_size(conclusion: str) -> Tuple[str, float]:
    """Map a reasoning conclusion string to a discrete ML-style signal and default size."""
    c = (conclusion or "").lower()
    if "strong_buy" in c or "strong buy" in c:
        return "STRONG_BUY", 0.1
    if "strong_sell" in c or "strong sell" in c:
        return "STRONG_SELL", 0.1
    if "buy" in c:
        return "BUY", 0.05
    if "sell" in c:
        return "SELL", 0.05
    return "HOLD", 0.0


def build_ml_evidence_from_orchestrator_result(result: Dict[str, Any]) -> MLEvidenceSnapshot:
    """Build ML evidence snapshot from a full MCP orchestrator prediction result dict."""
    from agent.core.ml_validator import ml_candidate_signal_from_validation
    from agent.core.strategy_types import MLValidationSnapshot

    symbol = str(result.get("symbol") or settings.trading_symbol or "BTCUSD")
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    mc = result.get("market_context") if isinstance(result.get("market_context"), dict) else {}
    models = result.get("models") if isinstance(result.get("models"), dict) else {}
    preds = result.get("model_predictions")
    if not isinstance(preds, list):
        preds = models.get("predictions") or []

    excerpt: Dict[str, Any] = {}
    if isinstance(mc, dict):
        for k in (
            "v43_gate_reject",
            "v43_training_forward_bars",
            "v43_dedicated_decision",
            "v43_execution_profile",
            "ml_validation",
            "strategy_candidate",
            "trade_score",
            "market_structure",
        ):
            if k in mc:
                excerpt[k] = mc[k]

    regime = None
    if isinstance(mc, dict):
        regime = mc.get("regime") or mc.get("v43_regime")

    ml_sig = str(decision.get("signal") or "HOLD")
    ml_conf = float(decision.get("confidence") or 0.0)
    ml_size = float(decision.get("position_size") or 0.0)

    ml_val_raw = mc.get("ml_validation") if isinstance(mc, dict) else None
    if isinstance(ml_val_raw, dict):
        try:
            snap = MLValidationSnapshot(
                expected_return=float(ml_val_raw.get("expected_return", 0.0) or 0.0),
                threshold=float(ml_val_raw.get("threshold", 0.005) or 0.005),
                short_threshold=float(ml_val_raw.get("short_threshold", 0.005) or 0.005),
                regime=str(ml_val_raw.get("regime", "neutral") or "neutral"),
                unc_scale=float(ml_val_raw.get("unc_scale", 1.0) or 1.0),
                uncertainty=float(ml_val_raw.get("uncertainty", 0.0) or 0.0),
                confirms_long=bool(ml_val_raw.get("confirms_long")),
                confirms_short=bool(ml_val_raw.get("confirms_short")),
                raw_long=bool(ml_val_raw.get("raw_long")),
                raw_short=bool(ml_val_raw.get("raw_short")),
                model_confidence=float(ml_val_raw.get("model_confidence", 0.0) or 0.0),
                model_prediction=float(ml_val_raw.get("model_prediction", 0.0) or 0.0),
                gate_reject=ml_val_raw.get("gate_reject"),
                final_long=bool(ml_val_raw.get("final_long")),
                final_short=bool(ml_val_raw.get("final_short")),
            )
            ml_sig, ml_conf, ml_size = ml_candidate_signal_from_validation(snap, prefer_gated=True)
        except (TypeError, ValueError):
            pass
    elif isinstance(mc, dict):
        v43_dec = mc.get("v43_dedicated_decision")
        if isinstance(v43_dec, dict) and v43_dec.get("ml_candidate_signal"):
            ml_sig = str(v43_dec.get("ml_candidate_signal") or ml_sig)
            ml_conf = float(v43_dec.get("confidence", ml_conf) or ml_conf)

    thesis_sig = None
    strat = mc.get("strategy_candidate") if isinstance(mc, dict) else None
    if isinstance(strat, dict):
        thesis_sig = strat.get("signal")

    trade_score_val = None
    ts = mc.get("trade_score") if isinstance(mc, dict) else None
    if isinstance(ts, dict):
        trade_score_val = ts.get("score")

    ml_confirms = None
    if isinstance(ml_val_raw, dict):
        ml_confirms = bool(
            ml_val_raw.get("final_long") or ml_val_raw.get("final_short")
        )

    return MLEvidenceSnapshot(
        symbol=symbol,
        source="v43_orchestrator",
        ml_candidate_signal=ml_sig,
        ml_candidate_confidence=ml_conf,
        ml_candidate_position_size=ml_size,
        consensus_signal=_opt_float(models.get("consensus_prediction")),
        consensus_confidence=_opt_float(models.get("consensus_confidence")),
        model_predictions=list(preds) if isinstance(preds, list) else [],
        v43_gate_reject=mc.get("v43_gate_reject") if isinstance(mc, dict) else None,
        v43_regime=str(regime) if regime is not None else None,
        market_context_excerpt=excerpt,
        thesis_signal=str(thesis_sig) if thesis_sig is not None else None,
        trade_score=_opt_float(trade_score_val),
        ml_confirms=ml_confirms,
    )


def build_ml_evidence_from_reasoning_context(
    symbol: str,
    market_context: Dict[str, Any],
    ml_candidate_signal: str,
    ml_candidate_confidence: float,
    ml_candidate_position_size: float,
    model_predictions: List[Dict[str, Any]],
) -> MLEvidenceSnapshot:
    """Build ML evidence when the pipeline came through standalone reasoning request."""
    mc = market_context if isinstance(market_context, dict) else {}
    excerpt: Dict[str, Any] = {}
    for k in ("v43_gate_reject", "v43_dedicated_decision", "v43_execution_profile"):
        if k in mc:
            excerpt[k] = mc[k]
    regime = mc.get("regime") or mc.get("v43_regime")
    return MLEvidenceSnapshot(
        symbol=symbol,
        source="reasoning_path",
        ml_candidate_signal=str(ml_candidate_signal or "HOLD"),
        ml_candidate_confidence=float(ml_candidate_confidence or 0.0),
        ml_candidate_position_size=float(ml_candidate_position_size or 0.0),
        consensus_signal=_opt_float(mc.get("consensus_signal")),
        consensus_confidence=_opt_float(mc.get("consensus_confidence")),
        model_predictions=list(model_predictions or []),
        v43_gate_reject=mc.get("v43_gate_reject"),
        v43_regime=str(regime) if regime is not None else None,
        market_context_excerpt=excerpt,
    )


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_signal(sig: str) -> str:
    s = str(sig or "HOLD").upper()
    if s not in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"):
        return "HOLD"
    return s


def _is_entry(sig: str) -> bool:
    return _normalize_signal(sig) in _ENTRY_SIGNALS


def _ml_gated_from_context(
    market_context: Optional[Dict[str, Any]],
    ml_evidence: MLEvidenceSnapshot,
) -> bool:
    """True when v43 post-gates passed (final_long/final_short) in market context."""
    mc = market_context if isinstance(market_context, dict) else {}
    ml_val = mc.get("ml_validation")
    if isinstance(ml_val, dict):
        return bool(ml_val.get("final_long") or ml_val.get("final_short"))
    excerpt = ml_evidence.market_context_excerpt or {}
    ml_val = excerpt.get("ml_validation")
    if isinstance(ml_val, dict):
        return bool(ml_val.get("final_long") or ml_val.get("final_short"))
    v43 = excerpt.get("v43_dedicated_decision")
    if isinstance(v43, dict):
        return bool(v43.get("final_long") or v43.get("final_short"))
    return False


def _thesis_blocks_gated_ml_adoption(thesis: ThesisVerdict) -> bool:
    """True when rule thesis explicitly vetoes adopting gated ML while thesis is HOLD."""
    if thesis.thesis_type in ("crisis_veto",):
        return True
    codes = {str(r) for r in (thesis.reason_codes or [])}
    if "thesis_direction_conflict" in codes:
        return True
    if any("veto" in c for c in codes):
        return True
    return False


def _same_direction(a: str, b: str) -> bool:
    sa, sb = _normalize_signal(a), _normalize_signal(b)
    if sa in ("BUY", "STRONG_BUY") and sb in ("BUY", "STRONG_BUY"):
        return True
    if sa in ("SELL", "STRONG_SELL") and sb in ("SELL", "STRONG_SELL"):
        return True
    return sa == sb == "HOLD"


def _multi_horizon_evidence_from_context(
    market_context: Dict[str, Any],
    ml_evidence: MLEvidenceSnapshot,
) -> Optional[MultiHorizonMLEvidence]:
    raw = market_context.get("multi_horizon_evidence")
    if raw is None:
        excerpt = ml_evidence.market_context_excerpt or {}
        raw = excerpt.get("multi_horizon_evidence")
    if isinstance(raw, dict) and raw.get("heads"):
        heads_raw = raw.get("heads") or {}
        payloads = {
            k: {
                "forward_bars": v.get("forward_bars"),
                "expected_return": v.get("expected_return"),
                "threshold": v.get("threshold"),
                "short_threshold": v.get("short_threshold"),
                "regime": v.get("regime"),
            }
            for k, v in heads_raw.items()
            if isinstance(v, dict)
        }
        mc = market_context if isinstance(market_context, dict) else {}
        meta = mc.get("v43_bundle_metadata")
        if not isinstance(meta, dict):
            excerpt = ml_evidence.market_context_excerpt or {}
            meta = excerpt.get("v43_bundle_metadata")
        if not isinstance(meta, dict):
            meta = {
                "model_family": "jacksparrow_v43_multihead",
                "primary_execution_horizon_bars": int(
                    raw.get("primary_execution_horizon_bars", 2) or 2
                ),
                "horizons": {
                    k: {
                        "forward_bars": v.get("forward_bars"),
                        "validation_metrics": {
                            "dynamic_threshold": v.get("threshold", 0.005),
                            "short_threshold": v.get("short_threshold", 0.005),
                        },
                    }
                    for k, v in payloads.items()
                },
            }
        return build_multi_horizon_evidence(payloads, meta)
    return None


def _ml_training_forward_bars(
    market_context: Dict[str, Any],
    ml_evidence: MLEvidenceSnapshot,
) -> int:
    raw = market_context.get("v43_training_forward_bars")
    if raw is None:
        excerpt = ml_evidence.market_context_excerpt or {}
        raw = excerpt.get("v43_training_forward_bars")
    return resolve_training_forward_bars(
        {"training_forward_bars": raw} if raw is not None else None,
        settings_fallback=int(getattr(settings, "jacksparrow_v43_forward_target_bars", 2) or 2),
    )


def _fuse_signals(
    ml_evidence: MLEvidenceSnapshot,
    thesis: ThesisVerdict,
    mode: str,
    conclusion: str,
    market_context: Optional[Dict[str, Any]] = None,
) -> PolicyVerdict:
    ml_sig = _normalize_signal(ml_evidence.ml_candidate_signal)
    th_sig = _normalize_signal(thesis.signal)
    ml_entry = _is_entry(ml_sig)
    th_entry = _is_entry(th_sig)

    reasons: List[str] = [f"fusion_mode={mode}", f"thesis_type={thesis.thesis_type}"]
    reasons.extend(thesis.reason_codes[:6])

    if mode == "ml_only":
        return _verdict_from_ml(ml_evidence, ml_sig, conclusion, reasons + ["fusion_ml_only"])

    if mode == "thesis_only":
        if th_entry:
            reasons.append("agent_thesis_entry")
            return PolicyVerdict(
                signal=th_sig,
                confidence=float(thesis.confidence),
                position_size=float(thesis.position_size or ml_evidence.ml_candidate_position_size or 0.05),
                reason_codes=reasons + ["agent_thesis_origin"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(thesis.confidence),
            position_size=0.0,
            reason_codes=reasons + ["thesis_hold"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=False,
        )

    if mode == "thesis_veto_ml":
        if th_sig == "HOLD" and thesis.thesis_type in ("crisis_veto", "flat") and any(
            "veto" in r for r in thesis.reason_codes
        ):
            return PolicyVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=reasons + ["thesis_veto_ml_active"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        if ml_entry:
            return _verdict_from_ml(
                ml_evidence, ml_sig, conclusion, reasons + ["thesis_veto_passed_ml_adopted"]
            )
        if th_entry:
            reasons.append("agent_thesis_entry")
            return PolicyVerdict(
                signal=th_sig,
                confidence=float(thesis.confidence),
                position_size=float(thesis.position_size or 0.05),
                reason_codes=reasons + ["agent_thesis_origin"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons + ["thesis_veto_hold"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=not ml_entry,
        )

    if mode == "ml_or_thesis":
        if ml_entry:
            return _verdict_from_ml(
                ml_evidence, ml_sig, conclusion, reasons + ["fusion_ml_or_thesis_ml"]
            )
        if th_entry:
            reasons.append("agent_thesis_entry")
            return PolicyVerdict(
                signal=th_sig,
                confidence=float(thesis.confidence),
                position_size=float(thesis.position_size or 0.05),
                reason_codes=reasons + ["fusion_ml_or_thesis_thesis", "agent_thesis_origin"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons + ["fusion_ml_or_thesis_hold"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=True,
        )

    if mode == "ml_and_thesis":
        mc = market_context if isinstance(market_context, dict) else {}
        if bool(getattr(settings, "jacksparrow_v43_require_horizon_fusion_match", True)):
            mh = _multi_horizon_evidence_from_context(mc, ml_evidence)
            th_h = int(thesis.intended_horizon_bars or 0)
            if mh is not None and th_h > 0:
                th_dir = "LONG" if th_sig in ("BUY", "STRONG_BUY") else (
                    "SHORT" if th_sig in ("SELL", "STRONG_SELL") else "FLAT"
                )
                ok, mh_reasons = validate_thesis_against_multi_horizon(
                    th_dir, th_h, mh
                )
                if not ok:
                    return PolicyVerdict(
                        signal="HOLD",
                        confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
                        position_size=0.0,
                        reason_codes=reasons + mh_reasons,
                        ml_evidence_id=ml_evidence.evidence_id,
                        adopted_ml_candidate=False,
                    )
                reasons.extend(mh_reasons[:4])
        if ml_entry and th_entry and _same_direction(ml_sig, th_sig):
            reasons.append("agent_thesis_confirms_ml")
            v = _verdict_from_ml(
                ml_evidence,
                ml_sig,
                conclusion,
                reasons + ["fusion_ml_and_thesis_agree"],
            )
            v.confidence = max(v.confidence, float(thesis.confidence))
            return v
        if (
            ml_entry
            and not th_entry
            and th_sig == "HOLD"
            and bool(getattr(settings, "agent_policy_adopt_gated_ml_when_thesis_neutral", True))
            and (
                bool(ml_evidence.ml_confirms)
                or _ml_gated_from_context(market_context, ml_evidence)
            )
            and not _thesis_blocks_gated_ml_adoption(thesis)
        ):
            return _verdict_from_ml(
                ml_evidence,
                ml_sig,
                conclusion,
                reasons + ["fusion_ml_gated_thesis_neutral"],
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons
            + [
                "fusion_ml_and_thesis_no_agreement",
                f"ml={ml_sig}",
                f"thesis={th_sig}",
            ],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=False,
        )

    return _verdict_from_ml(ml_evidence, ml_sig, conclusion, reasons + ["fusion_unknown_mode_fallback"])


def _verdict_from_ml(
    ml_evidence: MLEvidenceSnapshot,
    sig: str,
    conclusion: str,
    reasons: List[str],
) -> PolicyVerdict:
    if sig == "HOLD":
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons + ["agent_hold_ml_candidate_hold", "ml_evidence_supporting"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=True,
        )
    out_reasons = list(reasons) + [
        "agent_ratified_ml_evidence",
        "ml_evidence_supporting",
        f"ml_source={ml_evidence.source}",
    ]
    if conclusion:
        out_reasons.append("reasoning_conclusion_considered")
    return PolicyVerdict(
        signal=sig,
        confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
        position_size=float(ml_evidence.ml_candidate_position_size or 0.0),
        reason_codes=out_reasons,
        ml_evidence_id=ml_evidence.evidence_id,
        adopted_ml_candidate=True,
    )


class AgentPolicyEngine:
    """Evaluates ML evidence + rule thesis; emits :class:`PolicyVerdict` for the agent."""

    def __init__(self, thesis_engine: Optional[AgentThesisEngine] = None) -> None:
        self._thesis_engine = thesis_engine or agent_thesis_engine

    def evaluate(
        self,
        *,
        ml_evidence: MLEvidenceSnapshot,
        conclusion: str = "",
        market_context: Optional[Dict[str, Any]] = None,
        reasoning_chain: Optional[MCPReasoningChain] = None,
    ) -> PolicyVerdict:
        """Return the agent policy verdict for this cycle."""
        mc = market_context if isinstance(market_context, dict) else {}
        force_hold = bool(getattr(settings, "agent_policy_force_hold", False))
        if force_hold:
            return PolicyVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["agent_policy_force_hold", "veto_all_entries"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )

        mode = str(getattr(settings, "agent_policy_mode", "ml_only") or "ml_only").strip().lower()
        if mode not in _POLICY_MODES:
            logger.warning("agent_policy_unknown_mode", mode=mode, fallback="ml_only")
            mode = "ml_only"

        regime = ml_evidence.v43_regime or mc.get("regime") or mc.get("v43_regime")
        thesis = self._thesis_engine.evaluate(regime, mc)
        verdict = _fuse_signals(ml_evidence, thesis, mode, conclusion, market_context=mc)
        memory_scale = _memory_size_scale_from_reasoning(reasoning_chain)
        if memory_scale < 1.0 and verdict.position_size > 0:
            verdict = verdict.model_copy(
                update={
                    "position_size": float(verdict.position_size) * memory_scale,
                    "memory_size_scale": memory_scale,
                    "reason_codes": list(verdict.reason_codes)
                    + [f"memory_size_scale={memory_scale:.2f}"],
                }
            )
        elif memory_scale != 1.0:
            verdict = verdict.model_copy(update={"memory_size_scale": memory_scale})
        return verdict


def _memory_size_scale_from_reasoning(
    reasoning_chain: Optional[MCPReasoningChain],
) -> float:
    """Scale position size down when similar historical setups underperformed."""
    if reasoning_chain is None:
        return 1.0
    step2 = next((s for s in reasoning_chain.steps if s.step_number == 2), None)
    if step2 is None or not isinstance(step2.step_metadata, dict):
        return 1.0
    hr = step2.step_metadata.get("historical_win_rate")
    if hr is None:
        return 1.0
    try:
        win_rate = float(hr)
    except (TypeError, ValueError):
        return 1.0
    if win_rate < 0.40:
        return 0.8
    return 1.0


agent_policy_engine = AgentPolicyEngine()
