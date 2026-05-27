"""JackSparrow v43 five-gate filter (post raw threshold signal)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger(__name__)

GATE_STATE_REDIS_PREFIX = "gate_state"
GATE_STATE_DEFAULT_TTL_SECONDS = 86400
COLLAPSE_RATE_WINDOW = 20
COLLAPSE_RATE_HIGH_THRESHOLD = 0.85


def _gate_state_redis_key(symbol: str) -> str:
    sym = str(symbol or "").strip().upper() or "DEFAULT"
    return f"{GATE_STATE_REDIS_PREFIX}:{sym}"


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signals_raw": self.signals_raw,
            "rejected_pos_open": self.rejected_pos_open,
            "rejected_debounce": self.rejected_debounce,
            "rejected_freq_cap": self.rejected_freq_cap,
            "rejected_regime": self.rejected_regime,
            "rejected_edge": self.rejected_edge,
            "trades_executed": self.trades_executed,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "V43GateCounters":
        if not isinstance(data, dict):
            return cls()
        return cls(
            signals_raw=int(data.get("signals_raw") or 0),
            rejected_pos_open=int(data.get("rejected_pos_open") or 0),
            rejected_debounce=int(data.get("rejected_debounce") or 0),
            rejected_freq_cap=int(data.get("rejected_freq_cap") or 0),
            rejected_regime=int(data.get("rejected_regime") or 0),
            rejected_edge=int(data.get("rejected_edge") or 0),
            trades_executed=int(data.get("trades_executed") or 0),
        )


@dataclass
class V43GateState:
    """Mutable bar index / trade history for gates 2–3."""

    last_entry_bar_index: Optional[int] = None
    last_signal_bar_index: Optional[int] = None
    trade_timestamps_utc: List[datetime] = field(default_factory=list)
    trades_by_date: Dict[str, int] = field(default_factory=dict)
    counters: V43GateCounters = field(default_factory=V43GateCounters)
    current_regime: Optional[str] = None
    regime_bar_age: int = 0
    recent_collapse_samples: List[float] = field(default_factory=list)
    near_threshold_epsilon_bump: float = 0.0

    def note_regime(self, regime: str) -> None:
        """Track consecutive bars in the same regime label."""
        reg = str(regime or "neutral")
        if self.current_regime == reg:
            self.regime_bar_age = int(self.regime_bar_age or 0) + 1
        else:
            self.current_regime = reg
            self.regime_bar_age = 1

    def record_collapse_sample(self, collapse_rate: float) -> None:
        """Append collapse rate for rolling-window auto-adaptation."""
        try:
            sample = float(collapse_rate)
        except (TypeError, ValueError):
            return
        self.recent_collapse_samples.append(max(0.0, min(1.0, sample)))
        if len(self.recent_collapse_samples) > COLLAPSE_RATE_WINDOW:
            self.recent_collapse_samples = self.recent_collapse_samples[-COLLAPSE_RATE_WINDOW:]

    def rolling_collapse_rate(self) -> Optional[float]:
        if not self.recent_collapse_samples:
            return None
        return sum(self.recent_collapse_samples) / len(self.recent_collapse_samples)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_entry_bar_index": self.last_entry_bar_index,
            "last_signal_bar_index": self.last_signal_bar_index,
            "trade_timestamps_utc": [
                t.astimezone(timezone.utc).isoformat() for t in self.trade_timestamps_utc
            ],
            "trades_by_date": dict(self.trades_by_date),
            "counters": self.counters.to_dict(),
            "current_regime": self.current_regime,
            "regime_bar_age": int(self.regime_bar_age or 0),
            "recent_collapse_samples": list(self.recent_collapse_samples),
            "near_threshold_epsilon_bump": float(self.near_threshold_epsilon_bump or 0.0),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "V43GateState":
        if not isinstance(data, dict):
            return cls()
        ts_list: List[datetime] = []
        for raw in data.get("trade_timestamps_utc") or []:
            if isinstance(raw, str):
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    ts_list.append(parsed.astimezone(timezone.utc))
                except ValueError:
                    continue
        trades_by_date = data.get("trades_by_date")
        if not isinstance(trades_by_date, dict):
            trades_by_date = {}
        samples = data.get("recent_collapse_samples")
        if not isinstance(samples, list):
            samples = []
        return cls(
            last_entry_bar_index=data.get("last_entry_bar_index"),
            last_signal_bar_index=data.get("last_signal_bar_index"),
            trade_timestamps_utc=ts_list,
            trades_by_date={str(k): int(v) for k, v in trades_by_date.items()},
            counters=V43GateCounters.from_dict(data.get("counters")),
            current_regime=data.get("current_regime"),
            regime_bar_age=int(data.get("regime_bar_age") or 0),
            recent_collapse_samples=[float(x) for x in samples if x is not None],
            near_threshold_epsilon_bump=float(data.get("near_threshold_epsilon_bump") or 0.0),
        )

    def note_signal_decision(self, bar_index: int) -> None:
        """Stamp debounce after a gated BUY/SELL signal (before fill)."""
        self.last_signal_bar_index = int(bar_index)

    def note_entry(self, bar_index: int, ts: datetime) -> None:
        self.last_entry_bar_index = int(bar_index)
        self.trade_timestamps_utc.append(ts)
        key = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        self.trades_by_date[key] = self.trades_by_date.get(key, 0) + 1


async def load_gate_state_from_redis(
    symbol: str,
    redis_client: Any,
) -> V43GateState:
    """Load persisted gate state or return a fresh instance."""
    if redis_client is None:
        return V43GateState()
    key = _gate_state_redis_key(symbol)
    try:
        raw = await redis_client.get(key)
        if not raw:
            return V43GateState()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        return V43GateState.from_dict(payload)
    except Exception as e:
        logger.warning("v43_gate_state_load_failed", symbol=symbol, error=str(e))
        return V43GateState()


async def persist_gate_state(
    symbol: str,
    state: V43GateState,
    redis_client: Any,
    ttl: int = GATE_STATE_DEFAULT_TTL_SECONDS,
) -> None:
    """Persist gate state to Redis with TTL."""
    if redis_client is None:
        return
    key = _gate_state_redis_key(symbol)
    try:
        await redis_client.setex(key, int(ttl), json.dumps(state.to_dict()))
    except Exception as e:
        logger.warning("v43_gate_state_persist_failed", symbol=symbol, error=str(e))


def compute_regime_transition_risk(thesis_allowed_count: int) -> str:
    """Map count of regime-valid thesis strategies to transition risk label."""
    if thesis_allowed_count >= 2:
        return "low"
    if thesis_allowed_count == 1:
        return "medium"
    return "high"


def maybe_widen_epsilon_on_high_collapse(
    state: V43GateState,
    *,
    score_std: float = 0.0,
) -> Optional[float]:
    """Widen near-threshold epsilon when rolling collapse rate is sustained high."""
    rolling = state.rolling_collapse_rate()
    if rolling is None or rolling <= COLLAPSE_RATE_HIGH_THRESHOLD:
        return None
    bump = min(0.01, max(0.0, 0.5 * float(score_std or 0.0)))
    if bump <= 0:
        bump = 0.001
    state.near_threshold_epsilon_bump = min(0.02, state.near_threshold_epsilon_bump + bump)
    return bump


@dataclass
class V43GateResult:
    """Outcome after applying gates 2–5 (gate 1 is precomputed raw signal)."""

    allow: bool
    reject_reason: Optional[str] = None


def round_trip_cost_pct() -> float:
    """Round-trip cost on **price-return scale** (not leveraged PnL).

    ``expected_return`` from v43 is a raw forward price move fraction; gate 5
    compares ``edge = expected_return - threshold`` to this cost hurdle. Leverage
    affects position sizing elsewhere — it must not inflate the edge-vs-cost gate.
    """
    maker = float(getattr(settings, "jacksparrow_v43_maker_fee_rate", 0.0002) or 0.0)
    slip = float(getattr(settings, "jacksparrow_v43_slippage_pct", 0.0003) or 0.0)
    return 2.0 * (maker + slip)


@dataclass(frozen=True)
class Gate5EdgeMetrics:
    """Numeric breakdown for gate 5 (expected-return edge vs round-trip cost multiple)."""

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
    """Long-side gate 5 inputs (expected-return edge vs cost multiple)."""
    tp = float(getattr(settings, "jacksparrow_v43_take_profit_pct", 0.015) or 0.015)
    ratio = float(getattr(settings, "jacksparrow_v43_min_edge_cost_ratio", 0.2) or 0.2)
    rtc = round_trip_cost_pct()
    thr_f = float(thr)
    edge_pct = float(proba) - thr_f
    lhs = edge_pct
    rhs = ratio * rtc
    return Gate5EdgeMetrics(
        edge_pct=edge_pct, tp=tp, ratio=ratio, rtc=rtc, lhs=lhs, rhs=rhs
    )


def gate5_short_edge_metrics(proba: float, thr: float) -> Gate5EdgeMetrics:
    """Short-side gate 5 (symmetric negative edge)."""
    tp = float(getattr(settings, "jacksparrow_v43_take_profit_pct", 0.015) or 0.015)
    ratio = float(getattr(settings, "jacksparrow_v43_min_edge_cost_ratio", 0.2) or 0.2)
    rtc = round_trip_cost_pct()
    thr_f = float(thr)
    edge_pct = -float(proba) - thr_f
    lhs = edge_pct
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

    from agent.core.v43_runtime_horizon import effective_v43_trade_debounce_bars

    debounce_bars = effective_v43_trade_debounce_bars()
    debounce_ref = state.last_signal_bar_index
    bar_delta = (
        (current_bar_index - debounce_ref)
        if debounce_ref is not None
        else None
    )
    if (
        debounce_ref is not None
        and bar_delta is not None
        and bar_delta < debounce_bars
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

    from agent.core.v43_runtime_horizon import effective_v43_trade_debounce_bars

    debounce_bars = effective_v43_trade_debounce_bars()
    debounce_ref = state.last_signal_bar_index
    bar_delta = (
        (current_bar_index - debounce_ref)
        if debounce_ref is not None
        else None
    )
    if (
        debounce_ref is not None
        and bar_delta is not None
        and bar_delta < debounce_bars
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
