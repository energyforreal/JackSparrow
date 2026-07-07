"""Partial position scale-out (foundation stub for Phase 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

ScaleAction = Literal["none", "scale_out", "reduce_risk"]


@dataclass
class ScaleOutDecision:
    """Advisory scale-out decision (not yet wired to execution)."""

    action: ScaleAction
    fraction: float
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "fraction": self.fraction,
            "reason": self.reason,
        }


def evaluate_scale_out(
    position: Dict[str, Any],
    *,
    health_score: float,
    opportunity_score: float,
    min_health_for_scale: float = 85.0,
    scale_fraction: float = 0.5,
) -> ScaleOutDecision:
    """
    Propose partial scale-out when thesis remains valid but opportunity fades.

    Execution path not implemented — returns advisory decision only.
    """
    if health_score >= min_health_for_scale and opportunity_score < 45.0:
        return ScaleOutDecision(
            action="scale_out",
            fraction=scale_fraction,
            reason="opportunity_fade_lock_partial",
        )
    if health_score < 55.0 and opportunity_score < 35.0:
        return ScaleOutDecision(
            action="reduce_risk",
            fraction=0.25,
            reason="health_weakening_reduce_exposure",
        )
    return ScaleOutDecision(action="none", fraction=0.0)
