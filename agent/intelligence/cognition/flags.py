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
