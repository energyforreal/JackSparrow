"""Orchestrates cognition modules in acyclic dependency order."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from agent.intelligence.cognition.decision_context import DecisionContext, DecisionContextBuilder
from agent.intelligence.cognition.expectation_engine import evaluate_expectation
from agent.intelligence.cognition.flags import (
    cognition_expectation_enabled,
    cognition_memory_enabled,
    cognition_risk_enabled,
    cognition_scenario_enabled,
    cognition_scorer_enabled,
    cognition_selector_enabled,
    cognition_shadow_enabled,
)
from agent.intelligence.cognition.memory_engine import update_memory
from agent.intelligence.cognition.risk_intelligence import evaluate_risk_intelligence
from agent.intelligence.cognition.scenario_engine import evaluate_scenario
from agent.intelligence.cognition.strategy_scorer import score_strategies
from agent.intelligence.cognition.strategy_selector import select_strategies
from agent.intelligence.cognition.types import ExpectationState, MarketMemory, ScenarioState
from agent.intelligence.market_state_engine import market_state_engine

logger = structlog.get_logger()


def _run_module(enabled_flag: bool) -> bool:
    """Shadow mode runs all modules for logging; authoritative when flag on."""
    return cognition_shadow_enabled() or enabled_flag


def run_reasoning_cycle(
    *,
    builder: DecisionContextBuilder,
    symbol: str,
    bar_index: int,
    features: Dict[str, Any],
    narrative_tail: List[Dict[str, Any]],
    portfolio_heat: float = 0.0,
    daily_drawdown_pct: float = 0.0,
    prior_expectation: Optional[ExpectationState] = None,
    prior_scenario: Optional[ScenarioState] = None,
    narrative_new_events: Optional[List[Dict[str, Any]]] = None,
) -> DecisionContext:
    """Run cognition modules: Expectation → Memory → Scenario → Risk → Selector → Scorer."""
    understanding = builder._understanding  # noqa: SLF001
    regime = understanding.regime if understanding else "neutral"
    new_events = narrative_new_events or []

    inputs = builder.to_inputs(
        features=features,
        portfolio_heat=portfolio_heat,
        daily_drawdown_pct=daily_drawdown_pct,
    )

    if _run_module(cognition_expectation_enabled()):
        exp, art = evaluate_expectation(inputs, prior=prior_expectation)
        builder = builder.with_expectation(exp).append_artifact(art)
        inputs = builder.to_inputs(
            features=features,
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_drawdown_pct,
        )

    if _run_module(cognition_memory_enabled()) and understanding is not None:
        traj = market_state_engine.load(symbol)
        prev_mem: Optional[MarketMemory] = None
        traj_dict = traj.to_dict()
        if isinstance(traj_dict.get("memory"), dict):
            prev_mem = MarketMemory.from_dict(traj_dict["memory"])
        memory, art = update_memory(
            prev_mem,
            symbol=symbol,
            bar_index=bar_index,
            understanding=understanding,
            narrative_events=new_events or list(narrative_tail[-3:]),
            features=features,
            regime=regime,
        )
        builder = builder.with_memory(memory).append_artifact(art)
        builder = builder.with_behavioral_evidence(
            {k: float(v) for k, v in memory.behavioral_scores}
        )
        inputs = builder.to_inputs(
            features=features,
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_drawdown_pct,
        )

    if _run_module(cognition_scenario_enabled()):
        sc, art = evaluate_scenario(
            inputs,
            prior=prior_scenario,
            narrative_tail=narrative_tail,
        )
        builder = builder.with_scenario(sc).append_artifact(art)
        inputs = builder.to_inputs(
            features=features,
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_drawdown_pct,
        )

    if _run_module(cognition_risk_enabled()):
        risk, art = evaluate_risk_intelligence(inputs)
        builder = builder.with_risk_intelligence(risk).append_artifact(art)
        inputs = builder.to_inputs(
            features=features,
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_drawdown_pct,
        )

    run_selection = _run_module(cognition_selector_enabled()) or cognition_shadow_enabled()
    if run_selection:
        sel, art = select_strategies(inputs)
        builder = builder.with_strategy_selection(sel).append_artifact(art)
        inputs = builder.to_inputs(
            features=features,
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_drawdown_pct,
        )
        scores, art2 = score_strategies(inputs, sel)
        builder = builder.with_strategy_scores(scores).append_artifact(art2)

    ctx = builder.build()
    _persist_cognition(symbol, bar_index, ctx)
    return ctx


def _persist_cognition(symbol: str, bar_index: int, ctx: DecisionContext) -> None:
    """Persist expectation and memory slices to market state file."""
    try:
        traj = market_state_engine.load(symbol)
        data = traj.to_dict()
        data["bar_index"] = bar_index
        if ctx.expectation is not None:
            data["last_expectation"] = ctx.expectation.to_dict()
            data["last_forecast"] = ctx.expectation.to_dict()
        if ctx.memory is not None:
            data["memory"] = ctx.memory.to_dict()
            data["failed_breakout_count"] = ctx.memory.failed_breakout_count
        from agent.intelligence.market_state_engine import MarketStateTrajectory

        market_state_engine.persist(symbol, MarketStateTrajectory.from_dict(data))
    except Exception as exc:
        logger.warning("cognition_persist_failed", symbol=symbol, bar_index=bar_index, error=str(exc))
