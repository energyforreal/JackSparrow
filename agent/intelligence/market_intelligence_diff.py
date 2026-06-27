"""Detect material changes between MarketIntelligence snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from agent.core.config import settings
from agent.intelligence.market_intelligence import MarketIntelligence


@dataclass
class MaterialChange:
    """Summary of meaningful intelligence delta."""

    changed: bool
    reasons: List[str] = field(default_factory=list)


def diff_market_intelligence(
    previous: Optional[MarketIntelligence],
    current: MarketIntelligence,
) -> MaterialChange:
    """Compare snapshots; return whether downstream reasoning should run."""
    if previous is None:
        return MaterialChange(changed=True, reasons=["initial_snapshot"])

    reasons: List[str] = []
    min_conf_delta = float(
        getattr(settings, "market_intel_min_confidence_delta", 0.10) or 0.10
    )

    if bool(getattr(settings, "market_intel_regime_change_triggers", True)):
        if previous.regime != current.regime:
            reasons.append(f"regime:{previous.regime}->{current.regime}")

    if previous.structure.market_type != current.structure.market_type:
        reasons.append(
            f"structure:{previous.structure.market_type}->"
            f"{current.structure.market_type}"
        )

    if bool(getattr(settings, "market_intel_vol_expansion_triggers", True)):
        if previous.volatility_state != current.volatility_state:
            reasons.append(
                f"volatility:{previous.volatility_state}->"
                f"{current.volatility_state}"
            )

    if previous.liquidity_ok != current.liquidity_ok:
        reasons.append(
            f"liquidity:{previous.liquidity_ok}->{current.liquidity_ok}"
        )

    if previous.trend_bias != current.trend_bias:
        reasons.append(f"trend:{previous.trend_bias}->{current.trend_bias}")

    prev_sig = (previous.thesis_verdict or {}).get("signal")
    curr_sig = (current.thesis_verdict or {}).get("signal")
    if prev_sig != curr_sig:
        reasons.append(f"thesis:{prev_sig}->{curr_sig}")

    if abs(previous.confidence - current.confidence) >= min_conf_delta:
        reasons.append("confidence_delta")

    if previous.bar_index != current.bar_index:
        # New closed bar always updates intel; material if nothing else fired
        if not reasons:
            reasons.append("new_closed_bar")

    return MaterialChange(changed=bool(reasons), reasons=reasons)


def should_run_full_prediction(
    diff: MaterialChange,
    *,
    has_open_position: bool,
) -> bool:
    """Decide whether to run full ML/reasoning pipeline."""
    if has_open_position:
        return True
    if not bool(getattr(settings, "market_intel_diff_enabled", False)):
        return True
    if bool(getattr(settings, "market_intel_diff_log_only", True)):
        return True
    return diff.changed
