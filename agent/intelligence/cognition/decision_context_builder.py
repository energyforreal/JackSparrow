"""Build DecisionContext from legacy market_context and run cognition cycle."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

import structlog

from agent.intelligence.cognition.builders import (
    market_state_to_understanding,
    snapshot_from_market_context,
    understanding_from_market_context,
)
from agent.intelligence.cognition.decision_context import DecisionContext, DecisionContextBuilder
from agent.intelligence.cognition.flags import (
    cognition_cycle_enabled,
    cognition_expectation_enabled,
    cognition_memory_enabled,
    cognition_risk_enabled,
    cognition_scenario_enabled,
    cognition_scorer_enabled,
    cognition_selector_enabled,
    cognition_shadow_enabled,
)
from agent.intelligence.cognition.reasoning_cycle import run_reasoning_cycle
from agent.intelligence.cognition.types import CognitionMeta, MarketUnderstanding

logger = structlog.get_logger()


def build_decision_context_from_market_context(
    market_context: Dict[str, Any],
    *,
    cycle_id: Optional[str] = None,
    run_cycle: bool = True,
) -> DecisionContext:
    """Assemble DecisionContext; optionally run cognition modules in dependency order."""
    mc = market_context if isinstance(market_context, dict) else {}
    symbol = str(mc.get("symbol") or "BTCUSD").strip().upper()
    bar_index = int(mc.get("v43_closed_bar_index") or mc.get("bar_index") or 0)
    meta = CognitionMeta(
        symbol=symbol,
        bar_index=bar_index,
        cycle_id=cycle_id or str(uuid.uuid4()),
        schema_version="3.0",
    )

    builder = DecisionContextBuilder().with_meta(meta)
    understanding = understanding_from_market_context(mc)
    if understanding is None:
        snap = snapshot_from_market_context(mc)
        if snap is not None:
            understanding = market_state_to_understanding(snap)
    if understanding is not None:
        builder = builder.with_understanding(understanding)

    env = mc.get("environment_scores")
    if isinstance(env, dict):
        builder = builder.with_structural_evidence(
            {f"env_{k}": float(v) for k, v in env.items() if v is not None}
        )

    if run_cycle and cognition_cycle_enabled():
        narrative_tail = mc.get("narrative_tail")
        if not isinstance(narrative_tail, list):
            rb = mc.get("rule_based_pipeline")
            if isinstance(rb, dict):
                narrative_tail = rb.get("narrative_tail")
        narrative_new = mc.get("narrative_new_events")
        features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
        portfolio_heat = float(mc.get("portfolio_heat") or 0.0)
        daily_dd = float(mc.get("daily_drawdown_pct") or mc.get("agent_daily_drawdown_pct") or 0.0)
        return run_reasoning_cycle(
            builder=builder,
            symbol=symbol,
            bar_index=bar_index,
            features=features,
            narrative_tail=narrative_tail if isinstance(narrative_tail, list) else [],
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_dd,
            prior_expectation=_prior_expectation(mc),
            prior_scenario=_prior_scenario(mc),
            narrative_new_events=narrative_new if isinstance(narrative_new, list) else None,
        )

    return builder.build()


def _prior_expectation(mc: Dict[str, Any]) -> Optional[Any]:
    from agent.intelligence.cognition.types import ExpectationState

    traj = mc.get("market_state_trajectory")
    if isinstance(traj, dict):
        raw = traj.get("last_expectation") or traj.get("last_forecast")
        if isinstance(raw, dict):
            try:
                return ExpectationState.from_dict(raw)
            except (TypeError, ValueError):
                pass
    raw = mc.get("expectation")
    if isinstance(raw, dict):
        try:
            return ExpectationState.from_dict(raw)
        except (TypeError, ValueError):
            pass
    return None


def _prior_scenario(mc: Dict[str, Any]) -> Optional[Any]:
    from agent.intelligence.cognition.types import ScenarioState

    raw = mc.get("scenario")
    if isinstance(raw, dict):
        try:
            return ScenarioState.from_dict(raw)
        except (TypeError, ValueError):
            pass
    return None


def attach_decision_context_v3(market_context: Dict[str, Any]) -> Dict[str, Any]:
    """Attach decision_context_v3 to market_context when shadow/cycle enabled."""
    if not cognition_shadow_enabled() and not cognition_cycle_enabled():
        return market_context
    mc = market_context if isinstance(market_context, dict) else {}
    t0 = time.perf_counter()
    try:
        ctx = build_decision_context_from_market_context(mc, run_cycle=True)
        mc["decision_context_v3"] = ctx.to_dict()
        if cognition_expectation_enabled() and ctx.expectation is not None:
            mc["expectation"] = ctx.expectation.to_dict()
        if cognition_scenario_enabled() and ctx.scenario is not None:
            mc["scenario"] = ctx.scenario.to_dict()
        if cognition_memory_enabled() and ctx.memory is not None:
            mc["market_memory"] = ctx.memory.to_dict()
        if cognition_risk_enabled() and ctx.risk_intelligence is not None:
            mc["risk_intelligence"] = ctx.risk_intelligence.to_dict()
        if ctx.strategy_selection is not None:
            mc["strategy_selection"] = ctx.strategy_selection.to_dict()
        if ctx.strategy_scores is not None:
            mc["strategy_scores"] = ctx.strategy_scores.to_dict()
        eligible = ()
        if ctx.strategy_selection is not None:
            eligible = ctx.strategy_selection.eligible_ids()
        if eligible:
            mc["eligible_strategy_profiles"] = list(eligible)
        logger.info(
            "decision_context_v3_attached",
            symbol=ctx.meta.symbol,
            bar_index=ctx.meta.bar_index,
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            modules=[a.module_id for a in ctx.artifacts],
        )
    except Exception as exc:
        logger.warning("decision_context_v3_attach_failed", error=str(exc))
    return mc
