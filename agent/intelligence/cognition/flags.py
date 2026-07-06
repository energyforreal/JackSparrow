"""Cognition feature flags."""

from __future__ import annotations

from agent.core.config import settings


def cognition_shadow_enabled() -> bool:
    return bool(getattr(settings, "cognition_shadow_enabled", True))


def cognition_expectation_enabled() -> bool:
    return bool(getattr(settings, "cognition_expectation_enabled", False))


def cognition_memory_enabled() -> bool:
    return bool(getattr(settings, "cognition_memory_enabled", False))


def cognition_scenario_enabled() -> bool:
    return bool(getattr(settings, "cognition_scenario_enabled", False))


def cognition_risk_enabled() -> bool:
    return bool(getattr(settings, "cognition_risk_enabled", False))


def cognition_selector_enabled() -> bool:
    return bool(getattr(settings, "cognition_selector_enabled", False))


def cognition_scorer_enabled() -> bool:
    return bool(getattr(settings, "cognition_scorer_enabled", False))


def cognition_temporal_authority_enabled() -> bool:
    """When true, trade_score / ml_confirms / entry_quality use post-cognition thesis."""
    return bool(getattr(settings, "cognition_temporal_authority_enabled", False))


def log_cognition_config_effective() -> None:
    """Emit effective cognition flags at agent startup for deployment verification."""
    import structlog

    structlog.get_logger().info(
        "cognition_config_effective",
        shadow=cognition_shadow_enabled(),
        selector=cognition_selector_enabled(),
        scorer=cognition_scorer_enabled(),
        expectation=cognition_expectation_enabled(),
        memory=cognition_memory_enabled(),
        scenario=cognition_scenario_enabled(),
        risk=cognition_risk_enabled(),
        temporal_authority=cognition_temporal_authority_enabled(),
        cycle=cognition_cycle_enabled(),
    )


def cognition_cycle_enabled() -> bool:
    """Run full cognition cycle (shadow or authoritative per-module flags)."""
    return cognition_shadow_enabled() or any(
        (
            cognition_expectation_enabled(),
            cognition_memory_enabled(),
            cognition_scenario_enabled(),
            cognition_risk_enabled(),
            cognition_selector_enabled(),
            cognition_scorer_enabled(),
        )
    )
