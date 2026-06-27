"""Gate profile helper tests."""

from __future__ import annotations

from agent.core.config import settings
from agent.core.gate_profile import (
    mso_veto_enabled,
    state_head_hard_block_enabled,
    trade_score_hard_veto_enabled,
    v43_soft_ml_gates_enabled,
)


def test_permissive_profile_disables_market_vetoes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gate_profile", "permissive")
    monkeypatch.setattr(settings, "mso_shadow_mode", True)
    monkeypatch.setattr(settings, "jacksparrow_v43_state_head_policy_enabled", True)
    monkeypatch.setattr(settings, "agent_trade_score_hard_veto", False)
    assert not mso_veto_enabled()
    assert not state_head_hard_block_enabled()
    assert not trade_score_hard_veto_enabled()
    assert v43_soft_ml_gates_enabled()
