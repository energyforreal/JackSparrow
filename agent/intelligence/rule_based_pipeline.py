"""Rule-based decision pipeline — Understanding → Narrative → Gates → FSM."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.conviction import structural_confidence_to_fraction
from agent.core.market_structure import classify_market_structure
from agent.core.strategy_types import MarketStructureSnapshot
from agent.core.v43_signal_gates import V43GateState
from agent.intelligence.market_fsm import market_fsm
from agent.intelligence.market_narrative_engine import market_narrative_engine
from agent.intelligence.market_types import RuleBasedPipelineResult
from agent.intelligence.market_understanding_engine import market_understanding_engine
from agent.core.structural_gate_engine import structural_gate_engine
from agent.intelligence.market_state_engine import market_state_engine
from agent.intelligence.market_validation import validate_market
from agent.intelligence.regime_benchmark import derive_regime_benchmark
from agent.intelligence.signal_explainer import explain_signal

logger = structlog.get_logger()


def is_rule_based_mode() -> bool:
    mode = str(getattr(settings, "decision_engine_mode", "ml_legacy") or "ml_legacy")
    return mode.strip().lower() == "rule_based"


def is_shadow_enabled() -> bool:
    return bool(
        getattr(settings, "market_understanding_shadow_enabled", True)
        or getattr(settings, "structural_gate_shadow_enabled", True)
        or getattr(settings, "market_fsm_shadow_enabled", True)
    )


def should_enforce_fsm() -> bool:
    if is_rule_based_mode():
        return True
    return bool(getattr(settings, "market_fsm_enforce", False))


def _structural_confidence_score(snapshot: Any, gates: Any) -> float:
    base = {"low": 0.35, "medium": 0.55, "high": 0.75}.get(
        str(snapshot.confidence), 0.5
    )
    if gates.trade_allowed:
        passed = sum(1 for v in gates.categories.values() if v)
        base += 0.03 * passed
    return min(0.95, max(0.1, base))


class RuleBasedPipeline:
    """Orchestrates the rule-based intelligence layer."""

    def run_cycle(
        self,
        *,
        symbol: str,
        bar_index: int,
        features: Dict[str, Any],
        regime: str,
        thesis_signal: str = "HOLD",
        thesis_type: str = "flat",
        has_open_position: bool = False,
        structure: Optional[MarketStructureSnapshot] = None,
        gate_state: Optional[V43GateState] = None,
        contract_state: Any = None,
        features_history: Optional[List[Dict[str, Any]]] = None,
    ) -> RuleBasedPipelineResult:
        """Execute full rule-based pipeline for one closed bar."""
        if structure is None:
            structure = classify_market_structure(
                features,
                v43_regime=regime,
                contract_state=contract_state,
            )

        traj = market_state_engine.load(symbol)
        failed_breakout_count = int(traj.failed_breakout_count or 0)

        snapshot = market_understanding_engine.evaluate(
            symbol=symbol,
            bar_index=bar_index,
            features=features,
            regime=regime,
            structure=structure,
            thesis_signal=thesis_signal,
            thesis_type=thesis_type,
            failed_breakout_count=failed_breakout_count,
            features_history=features_history,
            contract_state=contract_state,
        )

        new_events, narrative_tail = market_narrative_engine.update_from_snapshot(
            snapshot, features=features
        )

        if any(e.event_type == "breakout_failed" for e in new_events):
            market_state_engine.update_from_cycle(
                symbol=symbol,
                bar_index=bar_index,
                regime=regime,
                evidence=_minimal_evidence(snapshot),
                breakout_failed=True,
            )
            failed_breakout_count += 1

        gates = structural_gate_engine.evaluate(
            snapshot=snapshot,
            structure=structure,
            narrative_tail=narrative_tail,
            failed_breakout_count=failed_breakout_count,
            has_open_position=has_open_position,
            gate_state=gate_state,
            new_events=new_events,
        )

        fsm_decision = market_fsm.evaluate(
            snapshot=snapshot,
            gates=gates,
            narrative_tail=narrative_tail,
            has_open_position=has_open_position,
        )

        conf = _structural_confidence_score(snapshot, gates)
        size_frac = structural_confidence_to_fraction(conf, fsm_decision.entry_signal)

        snapshot.regime_benchmark = derive_regime_benchmark(snapshot.to_dict())
        mv_result = validate_market(
            market_state=snapshot.to_dict(),
            gate_categories=gates.categories,
        )
        signal_expl = explain_signal(
            signal=fsm_decision.entry_signal,
            structural_confidence=conf,
            gate_categories=gates.categories,
            block_reasons=gates.block_reasons,
            fsm_state=fsm_decision.fsm_state,
            setup_type=gates.setup_type,
            market_state=snapshot.to_dict(),
        )

        result = RuleBasedPipelineResult(
            market_state=snapshot,
            narrative_events=new_events,
            narrative_tail=narrative_tail,
            structural_gates=gates,
            fsm_decision=fsm_decision,
            structural_confidence=conf,
            position_size_fraction=size_frac,
            market_validation=mv_result.to_dict(),
            signal_explanation=signal_expl,
        )
        _emit_cycle_shadow_logs(symbol=symbol, result=result)
        return result


def _emit_cycle_shadow_logs(*, symbol: str, result: RuleBasedPipelineResult) -> None:
    """Emit per-layer shadow logs (plan: understanding, gates, FSM)."""
    if not is_shadow_enabled():
        return
    snap = result.market_state
    gates = result.structural_gates
    fsm = result.fsm_decision
    logger.info(
        "structural_gate_shadow",
        symbol=symbol,
        trade_allowed=gates.trade_allowed,
        categories=gates.categories,
        block_reasons=gates.block_reasons,
        setup_type=gates.setup_type,
    )
    logger.info(
        "fsm_shadow_decision",
        symbol=symbol,
        fsm_state=fsm.fsm_state,
        entry_signal=fsm.entry_signal,
        exit_signal=fsm.exit_signal,
        abstention_reason=fsm.abstention_reason,
        position_lifecycle=fsm.position_lifecycle,
        thesis_health=fsm.thesis_health,
    )
    if result.narrative_events:
        for ev in result.narrative_events[-3:]:
            logger.info(
                "market_narrative_event",
                symbol=symbol,
                event_type=ev.event_type,
                bar_index=ev.bar_index,
                count=ev.count,
            )


def _minimal_evidence(snapshot: Any) -> Any:
    from agent.core.evidence_types import EvidenceBundle

    scores = {
        "trend": 0.7 if snapshot.trend != "neutral" else 0.4,
        "breakout": 0.3 if snapshot.breakout_status == "failed" else 0.6,
        "liquidity": 0.7 if snapshot.liquidity == "healthy" else 0.3,
    }
    return EvidenceBundle(scores=scores)


rule_based_pipeline = RuleBasedPipeline()


def log_shadow_comparison(
    *,
    symbol: str,
    pipeline: RuleBasedPipelineResult,
    live_signal: str,
    live_is_entry: bool,
) -> None:
    """Emit shadow comparison log against live ML/policy path."""
    rb_signal = pipeline.fsm_decision.entry_signal
    would_block = live_is_entry and rb_signal == "HOLD"
    disagrees = normalize_compare(live_signal) != normalize_compare(rb_signal)
    logger.info(
        "rule_based_pipeline_shadow",
        symbol=symbol,
        live_signal=live_signal,
        rule_based_signal=rb_signal,
        fsm_state=pipeline.fsm_decision.fsm_state,
        trade_allowed=pipeline.structural_gates.trade_allowed,
        setup_type=pipeline.structural_gates.setup_type,
        would_block_live_entry=would_block,
        fsm_disagrees_with_live=disagrees and live_is_entry,
        structural_confidence=pipeline.structural_confidence,
        gate_categories=pipeline.structural_gates.categories,
    )


def normalize_compare(signal: str) -> str:
    s = str(signal or "HOLD").upper()
    if s in ("LONG", "STRONG_LONG", "BUY"):
        return "LONG"
    if s in ("SHORT", "STRONG_SHORT", "SELL"):
        return "SHORT"
    return "HOLD"
