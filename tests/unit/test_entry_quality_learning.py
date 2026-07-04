"""Tests for post-trade entry quality calibration (PR7)."""

from agent.core.entry_quality import (
    apply_dimension_calibration_feedback,
    get_dimension_calibration,
)


def test_calibration_bounded_and_shadow_mode() -> None:
    before = get_dimension_calibration()
    adj = apply_dimension_calibration_feedback(
        {"structural": 0.5, "ml": 0.4},
        root_cause="poor_entry",
        pnl_usd=-1.0,
        shadow=True,
    )
    after = get_dimension_calibration()
    assert adj
    assert after == before


def test_calibration_applies_when_not_shadow() -> None:
    apply_dimension_calibration_feedback(
        {"structural": 0.5},
        root_cause="fee_dominated",
        pnl_usd=-0.5,
        shadow=False,
    )
    cal = get_dimension_calibration()
    assert "economic" in cal or "position_context" in cal
