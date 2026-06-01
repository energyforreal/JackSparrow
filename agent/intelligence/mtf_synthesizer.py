"""Multi-timeframe thesis alignment score."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.agent_thesis_engine import ThesisVerdict


def _signal_bucket(signal: str) -> str:
    s = str(signal).upper()
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return "HOLD"


def compute_mtf_alignment(
    thesis_5m: "ThesisVerdict",
    thesis_15m: "ThesisVerdict",
    thesis_1h: "ThesisVerdict",
) -> float:
    """Score 0–1: full agreement, partial (2+hold), conflict, or flat."""
    buckets = [
        _signal_bucket(thesis_5m.signal),
        _signal_bucket(thesis_15m.signal),
        _signal_bucket(thesis_1h.signal),
    ]
    buys = sum(1 for b in buckets if b == "BUY")
    sells = sum(1 for b in buckets if b == "SELL")
    holds = sum(1 for b in buckets if b == "HOLD")

    if buys == 3 or sells == 3:
        return 1.0
    if buys == 2 and holds == 1:
        return 0.6
    if sells == 2 and holds == 1:
        return 0.6
    if (buys == 2 and sells == 1) or (sells == 2 and buys == 1):
        return 0.2
    return 0.0
