"""JackSparrow v43 five-gate filter (post raw threshold signal)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class V43GateCounters:
    """Session counters for collapse-rate monitoring."""

    signals_raw: int = 0
    rejected_pos_open: int = 0
    rejected_debounce: int = 0
    rejected_freq_cap: int = 0
    rejected_regime: int = 0
    rejected_edge: int = 0
    trades_executed: int = 0

    def collapse_rate(self) -> float:
        return 1.0 - (self.trades_executed / max(self.signals_raw, 1))


@dataclass
class V43GateState:
    """Mutable bar index / trade history for gates 2–3."""

    last_entry_bar_index: Optional[int] = None
    trade_timestamps_utc: List[datetime] = field(default_factory=list)
    trades_by_date: Dict[str, int] = field(default_factory=dict)
    counters: V43GateCounters = field(default_factory=V43GateCounters)

    def note_entry(self, bar_index: int, ts: datetime) -> None:
        self.last_entry_bar_index = int(bar_index)
        self.trade_timestamps_utc.append(ts)
        key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        self.trades_by_date[key] = self.trades_by_date.get(key, 0) + 1


@dataclass
class V43GateResult:
    """Outcome after applying gates 2–5 (gate 1 is precomputed raw signal)."""

    allow: bool
    reject_reason: Optional[str] = None


def round_trip_cost_pct() -> float:
    """``2 * (maker_fee + slippage) * leverage`` from settings."""
    maker = float(getattr(settings, "jacksparrow_v43_maker_fee_rate", 0.0005) or 0.0)
    slip = float(getattr(settings, "jacksparrow_v43_slippage_pct", 0.0003) or 0.0)
    lev = int(getattr(settings, "jacksparrow_v43_leverage_assumption", 3) or 1)
    return 2.0 * (maker + slip) * float(max(1, lev))


@dataclass(frozen=True)
class Gate5EdgeMetrics:
    """Numeric breakdown for gate 5 (TP-scaled edge vs round-trip cost multiple)."""

    edge_pct: float
    tp: float
    ratio: float
    rtc: float
    lhs: float
    rhs: float

    @property
    def passes(self) -> bool:
        return bool(self.lhs >= self.rhs)


def gate5_long_edge_metrics(proba: float, thr: float) -> Gate5EdgeMetrics:
    """Long-side gate 5 inputs (``edge_pct * tp`` vs ``ratio * rtc``)."""
    tp = float(getattr(settings, "jacksparrow_v43_take_profit_pct", 0.015) or 0.015)
    ratio = float(getattr(settings, "jacksparrow_v43_min_edge_cost_ratio", 0.75) or 0.75)
    rtc = round_trip_cost_pct()
    thr_f = float(thr)
    edge_pct = (float(proba) - thr_f) / (1.0 - thr_f + 1e-9)
    lhs = edge_pct * tp
    rhs = ratio * rtc
    return Gate5EdgeMetrics(
        edge_pct=edge_pct, tp=tp, ratio=ratio, rtc=rtc, lhs=lhs, rhs=rhs
    )


def gate5_short_edge_metrics(proba: float, thr: float) -> Gate5EdgeMetrics:
    """Short-side gate 5 (symmetric negative edge)."""
    tp = float(getattr(settings, "jacksparrow_v43_take_profit_pct", 0.015) or 0.015)
    ratio = float(getattr(settings, "jacksparrow_v43_min_edge_cost_ratio", 0.75) or 0.75)
    rtc = round_trip_cost_pct()
    thr_f = float(thr)
    edge_pct = (-float(proba) - thr_f) / (1.0 - thr_f + 1e-9)
    lhs = edge_pct * tp
    rhs = ratio * rtc
    return Gate5EdgeMetrics(
        edge_pct=edge_pct, tp=tp, ratio=ratio, rtc=rtc, lhs=lhs, rhs=rhs
    )


def gate5_edge_ok(proba: float, thr: float) -> bool:
    """Min-edge-cost ratio vs TP-scaled relative edge."""
    return gate5_long_edge_metrics(proba, thr).passes


def gate5_short_edge_ok(proba: float, thr: float) -> bool:
    """Mirror of gate5 for symmetric short: proba and thr are on expected-return scale."""
    return gate5_short_edge_metrics(proba, thr).passes


def apply_post_threshold_gates_short(
    *,
    raw_short: bool,
    regime: str,
    current_bar_index: int,
    has_open_position: bool,
    state: V43GateState,
    now_utc: Optional[datetime] = None,
) -> V43GateResult:
    """Gates 2–5 after raw short signal ``proba < -thr`` when short execution is enabled."""
    now = now_utc or datetime.now(timezone.utc)
    if not raw_short:
        return V43GateResult(allow=False, reject_reason="below_threshold_short")

    state.counters.signals_raw += 1

    if has_open_position:
        state.counters.rejected_pos_open += 1
        return V43GateResult(allow=False, reject_reason="open_position")

    debounce_bars = int(getattr(settings, "jacksparrow_v43_trade_debounce_bars", 3) or 3)
    if (
        state.last_entry_bar_index is not None
        and (current_bar_index - state.last_entry_bar_index) < debounce_bars
    ):
        state.counters.rejected_debounce += 1
        return V43GateResult(allow=False, reject_reason="debounce")

    cutoff_h = now - timedelta(hours=1)
    recent = [t for t in state.trade_timestamps_utc if t > cutoff_h]
    state.trade_timestamps_utc = recent
    max_h = int(getattr(settings, "jacksparrow_v43_max_trades_per_hour", 2) or 2)
    if len(recent) >= max_h:
        state.counters.rejected_freq_cap += 1
        return V43GateResult(allow=False, reject_reason="freq_hourly")

    today = now.strftime("%Y-%m-%d")
    max_d = int(getattr(settings, "jacksparrow_v43_max_trades_per_day", 6) or 6)
    if state.trades_by_date.get(today, 0) >= max_d:
        state.counters.rejected_freq_cap += 1
        return V43GateResult(allow=False, reject_reason="freq_daily")

    if regime == "crisis":
        state.counters.rejected_regime += 1
        return V43GateResult(allow=False, reject_reason="crisis_regime")

    if bool(getattr(settings, "jacksparrow_v43_block_trending_entries", False)):
        if regime == "trending":
            state.counters.rejected_regime += 1
            return V43GateResult(allow=False, reject_reason="trending_blocked")

    return V43GateResult(allow=True, reject_reason=None)


def apply_gate5_min_edge_short(
    proba: float,
    thr: float,
    state: V43GateState,
) -> V43GateResult:
    """Gate 5 for short entries (after other gates passed)."""
    metrics = gate5_short_edge_metrics(proba, thr)
    if not metrics.passes:
        state.counters.rejected_edge += 1
        logger.info(
            "v43_gate5_rejected",
            side="short",
            proba=proba,
            thr=thr,
            edge_pct=metrics.edge_pct,
            tp=metrics.tp,
            ratio=metrics.ratio,
            rtc=metrics.rtc,
            lhs=metrics.lhs,
            rhs=metrics.rhs,
        )
        return V43GateResult(allow=False, reject_reason="min_edge_cost")
    return V43GateResult(allow=True, reject_reason=None)


def apply_post_threshold_gates(
    *,
    raw_long: bool,
    regime: str,
    current_bar_index: int,
    has_open_position: bool,
    state: V43GateState,
    now_utc: Optional[datetime] = None,
) -> V43GateResult:
    """Gates 2–5 after raw signal (proba > thr) is True.

    Args:
        raw_long: True if model output passed threshold (gate 1).
        regime: ``regime_label`` from feature row.
        current_bar_index: Monotonic 5m bar index (e.g. ``len(df5m) - 1`` for last row).
        has_open_position: True if already long/short — blocks new entry.
        state: Debounce / frequency state.
        now_utc: Clock for hourly/daily caps.

    Returns:
        ``V43GateResult`` with ``allow`` False if any gate fails.
    """
    now = now_utc or datetime.now(timezone.utc)
    if not raw_long:
        return V43GateResult(allow=False, reject_reason="below_threshold")

    state.counters.signals_raw += 1

    if has_open_position:
        state.counters.rejected_pos_open += 1
        return V43GateResult(allow=False, reject_reason="open_position")

    debounce_bars = int(getattr(settings, "jacksparrow_v43_trade_debounce_bars", 3) or 3)
    if (
        state.last_entry_bar_index is not None
        and (current_bar_index - state.last_entry_bar_index) < debounce_bars
    ):
        state.counters.rejected_debounce += 1
        return V43GateResult(allow=False, reject_reason="debounce")

    cutoff_h = now - timedelta(hours=1)
    recent = [t for t in state.trade_timestamps_utc if t > cutoff_h]
    state.trade_timestamps_utc = recent
    max_h = int(getattr(settings, "jacksparrow_v43_max_trades_per_hour", 2) or 2)
    if len(recent) >= max_h:
        state.counters.rejected_freq_cap += 1
        return V43GateResult(allow=False, reject_reason="freq_hourly")

    today = now.strftime("%Y-%m-%d")
    max_d = int(getattr(settings, "jacksparrow_v43_max_trades_per_day", 6) or 6)
    if state.trades_by_date.get(today, 0) >= max_d:
        state.counters.rejected_freq_cap += 1
        return V43GateResult(allow=False, reject_reason="freq_daily")

    if regime == "crisis":
        state.counters.rejected_regime += 1
        return V43GateResult(allow=False, reject_reason="crisis_regime")

    if bool(getattr(settings, "jacksparrow_v43_block_trending_entries", False)):
        if regime == "trending":
            state.counters.rejected_regime += 1
            return V43GateResult(allow=False, reject_reason="trending_blocked")

    return V43GateResult(allow=True, reject_reason=None)


def apply_gate5_min_edge(
    proba: float,
    thr: float,
    state: V43GateState,
) -> V43GateResult:
    """Gate 5 only (needs proba/thr after other gates passed)."""
    metrics = gate5_long_edge_metrics(proba, thr)
    if not metrics.passes:
        state.counters.rejected_edge += 1
        logger.info(
            "v43_gate5_rejected",
            side="long",
            proba=proba,
            thr=thr,
            edge_pct=metrics.edge_pct,
            tp=metrics.tp,
            ratio=metrics.ratio,
            rtc=metrics.rtc,
            lhs=metrics.lhs,
            rhs=metrics.rhs,
        )
        return V43GateResult(allow=False, reject_reason="min_edge_cost")
    return V43GateResult(allow=True, reject_reason=None)
