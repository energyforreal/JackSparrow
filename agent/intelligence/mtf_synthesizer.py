"""Multi-timeframe thesis alignment score."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.agent_thesis_engine import ThesisVerdict


def compute_mtf_alignment(
    thesis_5m: "ThesisVerdict",
    thesis_15m: "ThesisVerdict",
    thesis_1h: "ThesisVerdict",
) -> float:
    signals = [
        str(thesis_5m.signal).upper(),
        str(thesis_15m.signal).upper(),
        str(thesis_1h.signal).upper(),
    ]
    buys = sum(1 for s in signals if "BUY" in s)
    sells = sum(1 for s in signals if "SELL" in s)
    if buys == 3 or sells == 3:
        return 1.0
    if buys == 2 or sells == 2:
        return 0.6
    return 0.0
