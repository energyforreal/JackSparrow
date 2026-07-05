"""Strategy profile registry."""

from __future__ import annotations

from typing import Dict, Tuple

from agent.intelligence.cognition.types import StrategyProfile

_PROFILES: Dict[str, StrategyProfile] = {
    "breakout": StrategyProfile(
        id="breakout",
        supported_scenarios=("compression", "expansion", "accumulation"),
        expectation_thresholds=(
            ("breakout_likelihood", (0.55, 1.0)),
            ("reversal_risk", (0.0, 0.45)),
        ),
        risk_floor=0.25,
        horizon_minutes=60,
    ),
    "trend_continuation": StrategyProfile(
        id="trend_continuation",
        supported_scenarios=("markup", "markdown", "expansion"),
        expectation_thresholds=(
            ("trend_persistence", (0.6, 1.0)),
            ("reversal_risk", (0.0, 0.35)),
        ),
        risk_floor=0.3,
        horizon_minutes=30,
    ),
    "mean_reversion": StrategyProfile(
        id="mean_reversion",
        supported_scenarios=("range", "accumulation", "distribution"),
        expectation_thresholds=(
            ("breakout_likelihood", (0.0, 0.45)),
            ("reversal_risk", (0.4, 1.0)),
        ),
        risk_floor=0.25,
        horizon_minutes=10,
    ),
    "basis_crowding": StrategyProfile(
        id="basis_crowding",
        supported_scenarios=("markup", "markdown", "range"),
        expectation_thresholds=(),
        risk_floor=0.2,
        horizon_minutes=60,
    ),
    "funding_crowding": StrategyProfile(
        id="funding_crowding",
        supported_scenarios=("markup", "markdown", "liquidity_grab"),
        expectation_thresholds=(),
        risk_floor=0.2,
        horizon_minutes=60,
    ),
    "pullback": StrategyProfile(
        id="pullback",
        supported_scenarios=("markup", "markdown"),
        expectation_thresholds=(("trend_persistence", (0.5, 1.0)),),
        risk_floor=0.3,
        horizon_minutes=30,
        enabled=False,
    ),
    "liquidity_sweep": StrategyProfile(
        id="liquidity_sweep",
        supported_scenarios=("liquidity_grab",),
        expectation_thresholds=(("reversal_risk", (0.5, 1.0)),),
        risk_floor=0.2,
        horizon_minutes=30,
        enabled=False,
    ),
    "exhaustion": StrategyProfile(
        id="exhaustion",
        supported_scenarios=("trend_exhaustion",),
        expectation_thresholds=(("reversal_risk", (0.55, 1.0)),),
        risk_floor=0.25,
        horizon_minutes=60,
        enabled=False,
    ),
}


def all_profiles() -> Tuple[StrategyProfile, ...]:
    return tuple(_PROFILES.values())


def get_profile(profile_id: str) -> StrategyProfile | None:
    return _PROFILES.get(str(profile_id).strip().lower())


def enabled_profiles() -> Tuple[StrategyProfile, ...]:
    return tuple(p for p in _PROFILES.values() if p.enabled)
