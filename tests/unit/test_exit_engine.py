"""Unit tests for EV exit engine."""

from agent.core.continuation_thesis import ContinuationResult
from agent.core.exit_engine import decide_exit
from agent.core.position_intelligence import PositionQuality


def _quality(
    health: float,
    opportunity: float,
    *,
    opposite: bool = False,
    would_enter: bool = True,
    thesis_valid: bool = True,
) -> PositionQuality:
    return PositionQuality(
        health_score=health,
        opportunity_score=opportunity,
        conviction_now=0.6,
        conviction_at_entry=0.65,
        conviction_delta=-0.05,
        continuation=ContinuationResult(
            alignment=0.7,
            would_enter_same_side_now=would_enter,
            invalidation_codes=[],
            improvement_codes=[],
        ),
        opposite=opposite,
        opposite_reason="",
        thesis_valid=thesis_valid,
    )


def test_fee_aware_hold_july2_pattern() -> None:
    """health=48, opportunity=65 should HOLD under EV arbiter."""
    position = {
        "side": "long",
        "entry_price": 60000.0,
        "current_price": 60100.0,
    }
    quality = _quality(health=48.0, opportunity=82.0)
    decision = decide_exit(position, quality)
    assert decision.should_exit is False
    assert decision.fee_aware_hold is True


def test_opposite_signal_exits() -> None:
    position = {"side": "long", "entry_price": 60000.0, "current_price": 59900.0}
    quality = _quality(health=80.0, opportunity=80.0, opposite=True)
    quality.opposite_reason = "opposite_entry_signal"
    decision = decide_exit(position, quality)
    assert decision.should_exit is True
