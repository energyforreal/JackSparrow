"""Market memory with time-decay on behavioral events."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from agent.core.config import settings
from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.types import BehavioralEvent, MarketMemory, MarketUnderstanding

_NARRATIVE_BEHAVIORAL_MAP = {
    "breakout_failed": "failed_breakout",
    "liquidity_sweep": "liquidity_sweep",
    "resistance_test": "rejection",
    "support_test": "rejection",
    "breakout_attempt": "false_signal",
    "retest_failed": "false_signal",
}


def _half_life_bars() -> float:
    return float(getattr(settings, "cognition_memory_decay_half_life_bars", 10) or 10)


def decay_weight(age_bars: int, *, half_life: Optional[float] = None) -> float:
    """Exponential decay: weight at age_bars from event."""
    hl = half_life if half_life is not None else _half_life_bars()
    if hl <= 0:
        return 1.0
    return math.exp(-max(0, age_bars) / hl)


def _apply_decay_to_events(
    events: Tuple[BehavioralEvent, ...],
    current_bar: int,
) -> Tuple[BehavioralEvent, ...]:
    hl = _half_life_bars()
    out: List[BehavioralEvent] = []
    for ev in events:
        age = max(0, current_bar - ev.bar_index)
        w = decay_weight(age, half_life=hl)
        if w >= 0.05:
            out.append(BehavioralEvent(ev.event_type, ev.bar_index, w))
    return tuple(out)


def _sum_weighted(events: Tuple[BehavioralEvent, ...], event_type: str) -> float:
    return sum(e.weight for e in events if e.event_type == event_type)


def update_memory(
    prev: Optional[MarketMemory],
    *,
    symbol: str,
    bar_index: int,
    understanding: Optional[MarketUnderstanding],
    narrative_events: List[Dict[str, Any]],
    features: Dict[str, Any],
    regime: str = "neutral",
) -> Tuple[MarketMemory, ReasoningArtifact]:
    """Update compact market memory from narrative deltas."""
    t0 = time.perf_counter()
    prev_events: List[BehavioralEvent] = list(prev.behavioral_events if prev else ())
    prev_regime = list(prev.regime_history if prev else ())

    for ev in narrative_events or []:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("event_type") or "")
        mapped = _NARRATIVE_BEHAVIORAL_MAP.get(et)
        if mapped:
            prev_events.append(
                BehavioralEvent(mapped, int(ev.get("bar_index") or bar_index), 1.0)
            )

    decayed = _apply_decay_to_events(tuple(prev_events), bar_index)
    max_events = int(getattr(settings, "cognition_memory_max_events", 50) or 50)
    decayed = decayed[-max_events:]

    failed_count = prev.failed_breakout_count if prev else 0
    for ev in narrative_events or []:
        if isinstance(ev, dict) and ev.get("event_type") == "breakout_failed":
            failed_count += 1

    trend_dur = understanding.trend_age_candles if understanding else 0
    range_dur = prev.range_duration_bars if prev else 0
    if understanding is not None and understanding.trend == "neutral":
        range_dur += 1
    else:
        range_dur = 0

    hh_hl = "neutral"
    h_trend = float(features.get("h_trend") or 0.0)
    if h_trend > 0.1:
        hh_hl = "bull"
    elif h_trend < -0.1:
        hh_hl = "bear"

    prev_regime.append(str(regime))
    regime_hist = tuple(prev_regime[-20:])

    last_false: Optional[int] = None
    for ev in reversed(decayed):
        if ev.event_type == "false_signal":
            last_false = bar_index - ev.bar_index
            break

    behavioral_scores = (
        ("failed_breakout", _sum_weighted(decayed, "failed_breakout")),
        ("liquidity_sweep", _sum_weighted(decayed, "liquidity_sweep")),
        ("rejection", _sum_weighted(decayed, "rejection")),
        ("false_signal", _sum_weighted(decayed, "false_signal")),
    )

    memory = MarketMemory(
        symbol=symbol,
        bar_index=bar_index,
        failed_breakout_count=failed_count,
        failed_breakout_weighted=_sum_weighted(decayed, "failed_breakout"),
        liquidity_sweep_weighted=_sum_weighted(decayed, "liquidity_sweep"),
        rejection_weighted=_sum_weighted(decayed, "rejection"),
        range_duration_bars=range_dur,
        trend_duration_bars=trend_dur,
        hh_hl_sequence=hh_hl,
        regime_history=regime_hist,
        last_false_signal_bars_ago=last_false,
        behavioral_events=decayed,
        behavioral_scores=behavioral_scores,
    )
    artifact = ReasoningArtifact(
        module_id="memory",
        confidence=0.7,
        reason_codes=(f"memory_events={len(decayed)}",),
        output=memory.to_dict(),
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return memory, artifact
