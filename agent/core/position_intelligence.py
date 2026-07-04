"""Post-entry position quality intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from agent.core.continuation_thesis import ContinuationResult


@dataclass
class PositionQuality:
    """Aggregated post-entry position quality metrics."""

    health_score: float
    opportunity_score: float
    conviction_now: float
    conviction_at_entry: float
    conviction_delta: float
    continuation: ContinuationResult
    opposite: bool
    opposite_reason: str
    invalidation_reasons: List[str] = field(default_factory=list)
    opportunity_reasons: List[str] = field(default_factory=list)
    health_breakdown: Dict[str, Any] = field(default_factory=dict)
    flip_score: float = 0.0
    thesis_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_score": self.health_score,
            "opportunity_score": self.opportunity_score,
            "conviction_now": self.conviction_now,
            "conviction_at_entry": self.conviction_at_entry,
            "conviction_delta": self.conviction_delta,
            "opposite": self.opposite,
            "opposite_reason": self.opposite_reason,
            "flip_score": self.flip_score,
            "thesis_valid": self.thesis_valid,
            "health_breakdown": dict(self.health_breakdown),
            "continuation": self.continuation.to_dict(),
        }


def evaluate_position_quality(
    position: Dict[str, Any],
    entry_snapshot: Dict[str, Any],
    live_mc: Dict[str, Any],
) -> PositionQuality:
    """Compute position quality from continuation, health, and opportunity."""
    from agent.core.continuation_thesis import evaluate_continuation
    from agent.core.trade_lifecycle_engine import (
        _compute_health_score,
        _compute_opportunity_score,
        _conviction_from_context,
        _f,
        _flip_score,
        _opposite_signal_inputs,
        _position_side,
    )

    symbol = str(position.get("symbol") or live_mc.get("symbol") or "")
    pos_side = _position_side(position)

    conviction_at_entry = _f(position.get("conviction_at_entry"), 0.5)
    conviction_now = _conviction_from_context(live_mc)
    conviction_delta = conviction_now - conviction_at_entry

    continuation = evaluate_continuation(position, entry_snapshot, live_mc)
    flip_score = _flip_score(live_mc, pos_side, symbol)
    opposite, opp_reason = _opposite_signal_inputs(live_mc, pos_side)

    health, inv_reasons, health_breakdown = _compute_health_score(
        continuation, conviction_delta, flip_score, live_mc, opposite
    )
    opportunity, opp_reasons = _compute_opportunity_score(
        continuation, conviction_delta, live_mc
    )

    critical = {"fsm_thesis_broken", "ema_death_cross", "ema_golden_cross"}
    thesis_valid = not bool(set(continuation.invalidation_codes) & critical)

    return PositionQuality(
        health_score=health,
        opportunity_score=opportunity,
        conviction_now=conviction_now,
        conviction_at_entry=conviction_at_entry,
        conviction_delta=conviction_delta,
        continuation=continuation,
        opposite=opposite,
        opposite_reason=opp_reason,
        invalidation_reasons=inv_reasons,
        opportunity_reasons=opp_reasons,
        health_breakdown=health_breakdown,
        flip_score=flip_score,
        thesis_valid=thesis_valid,
    )
