"""Map thesis verdict to synthetic expected_return for pipeline compatibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.agent_thesis_engine import ThesisVerdict

_SIGNAL_TO_RETURN = {
    "STRONG_BUY": 0.025,
    "BUY": 0.012,
    "HOLD": 0.0,
    "SELL": -0.012,
    "STRONG_SELL": -0.025,
}

# Thesis confidence is already in [~0.6, 0.92]; avoid double-shrinking magnitude vs threshold.
_CONFIDENCE_FLOOR = 0.5


def compute_direction_signal(thesis: "ThesisVerdict") -> float:
    """Map thesis signal to signed expected_return for IC heads."""
    base = _SIGNAL_TO_RETURN.get(str(thesis.signal).upper(), 0.0)
    if base == 0.0:
        return 0.0
    conf = float(getattr(thesis, "confidence", 0.0) or 0.0)
    scale = max(conf, _CONFIDENCE_FLOOR)
    return float(base * scale)
