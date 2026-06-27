"""Gate profile helpers: permissive (evidence-based) vs strict (legacy reject stack)."""

from __future__ import annotations

from agent.core.config import settings

GATE_PROFILE_PERMISSIVE = "permissive"
GATE_PROFILE_BALANCED = "balanced"
GATE_PROFILE_STRICT = "strict"

_VALID_PROFILES = frozenset({GATE_PROFILE_PERMISSIVE, GATE_PROFILE_BALANCED, GATE_PROFILE_STRICT})


def gate_profile() -> str:
    raw = str(getattr(settings, "gate_profile", GATE_PROFILE_PERMISSIVE) or GATE_PROFILE_PERMISSIVE)
    p = raw.strip().lower()
    return p if p in _VALID_PROFILES else GATE_PROFILE_PERMISSIVE


def is_permissive_gate_profile() -> bool:
    return gate_profile() == GATE_PROFILE_PERMISSIVE


def is_strict_gate_profile() -> bool:
    return gate_profile() == GATE_PROFILE_STRICT


def evidence_based_sizing_enabled() -> bool:
    return bool(getattr(settings, "evidence_based_sizing", True))


def trade_score_hard_veto_enabled() -> bool:
    if is_permissive_gate_profile():
        return bool(getattr(settings, "agent_trade_score_hard_veto", False))
    return bool(getattr(settings, "agent_trade_score_hard_veto", False))


def mso_veto_enabled() -> bool:
    if bool(getattr(settings, "mso_shadow_mode", False)):
        return False
    if is_permissive_gate_profile():
        return False
    return bool(getattr(settings, "mso_model_enabled", False))


def state_head_hard_block_enabled() -> bool:
    if is_permissive_gate_profile():
        return False
    return bool(getattr(settings, "jacksparrow_v43_state_head_policy_enabled", False))


def v43_soft_ml_gates_enabled() -> bool:
    """When True, gate-5 and uncertainty do not hard-reject in permissive profile."""
    return is_permissive_gate_profile() or not is_strict_gate_profile()


def thesis_soft_evidence_enabled() -> bool:
    return bool(getattr(settings, "agent_thesis_soft_evidence_mode", True))
