"""Deferred PR6: consolidated decision pipeline behind feature flag."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.core.config import settings
from agent.events.schemas import PolicyVerdict


def unified_pipeline_active() -> bool:
    return bool(getattr(settings, "unified_pipeline_enabled", False))


def resolve_authoritative_verdict(
    *,
    policy_verdict: PolicyVerdict,
    reasoning_chain: Optional[Any] = None,
    entry_quality: Optional[Dict[str, Any]] = None,
) -> PolicyVerdict:
    """When unified pipeline is enabled, apply adjudication + quality in one place."""
    if not unified_pipeline_active():
        return policy_verdict
    from agent.core.agent_policy_engine import apply_adjudication_authority
    from agent.core.entry_quality import EntryQualityResult, apply_entry_quality_policy

    verdict = apply_adjudication_authority(policy_verdict, reasoning_chain)
    eq = None
    if isinstance(entry_quality, dict):
        eq = EntryQualityResult(
            quality_score=float(entry_quality.get("quality_score") or 0.0),
            passed=bool(entry_quality.get("passed", False)),
            dimensions=dict(entry_quality.get("dimensions") or {}),
            reason_codes=list(entry_quality.get("reason_codes") or []),
            required_ml_confirmation=bool(
                entry_quality.get("required_ml_confirmation", False)
            ),
        )
    mc_ml_confirms = False
    return apply_entry_quality_policy(verdict, eq, mc_ml_confirms)
