"""Unit tests for scenario-aware TLE health scoring."""

from unittest.mock import MagicMock

import pytest

from agent.core.trade_lifecycle_engine import _compute_health_score, _scenario_health_adjustment
from agent.core.continuation_thesis import ContinuationResult


def _continuation(**kwargs) -> ContinuationResult:
    base = {
        "alignment": 0.8,
        "would_enter_same_side_now": True,
        "invalidation_codes": [],
        "improvement_codes": [],
    }
    base.update(kwargs)
    return ContinuationResult(**base)


def test_scenario_phase_shift_penalty() -> None:
    live_mc = {
        "decision_context_v3": {
            "scenario": {
                "revision_reason": "phase_shift_markup_to_range",
                "primary": "range",
            }
        }
    }
    delta, reasons = _scenario_health_adjustment(live_mc, "long")
    assert delta < 0
    assert any("phase_shift" in r for r in reasons)


@pytest.fixture
def mock_settings(monkeypatch):
    s = MagicMock()
    s.trade_lifecycle_conviction_exit_delta = -0.25
    s.trade_lifecycle_conviction_penalty_soften_alignment = 0.70
    s.trade_lifecycle_flip_exit_score = 0.70
    monkeypatch.setattr("agent.core.trade_lifecycle_engine.settings", s)
    return s


def test_conviction_penalty_softened_when_aligned(mock_settings) -> None:
    cont = _continuation(alignment=0.85)
    health, _, breakdown = _compute_health_score(
        cont, -0.30, 0.0, {}, False, position_side="long"
    )
    assert breakdown["penalties"].get("conviction_drop_softened") == -12.0
    assert health >= 70.0
