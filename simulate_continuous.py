#!/usr/bin/env python3
"""
JackSparrow v43 — Comprehensive Continuous Simulation Framework
================================================================

Simulates real-world trading conditions using synthetic data fed continuously
through ALL agent components on a compressed timescale.

This is NOT a static snapshot test — it continuously feeds rolling windows of
synthetic bars into the full pipeline (ML inference → multi-horizon evidence →
market structure → thesis engine → v43 gates → trade scorer → policy engine →
portfolio guard → paper execution), simulates position management (SL/TP, time
exit), tracks P&L, and produces a detailed JSON + HTML report.

Usage:
    python simulate_continuous.py
    python simulate_continuous.py --bars 400 --seed 42 --symbol BTCUSD
    python simulate_continuous.py --no-html   # JSON only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
import traceback
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── repo root ──────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))

# ── silence structlog noise during simulation ──────────────────────────────
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("STRUCTLOG_LEVEL", "WARNING")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from agent.testing.scenario_env import load_scenario_env
load_scenario_env()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Synthetic Market Data Generator
# ═══════════════════════════════════════════════════════════════════════════

class MarketRegime:
    CHOP        = "chop"
    BULL_TREND  = "bull_trend"
    BEAR_TREND  = "bear_trend"
    BREAKOUT    = "breakout"
    FAKE_BREAK  = "fake_breakout"
    REVERSAL    = "reversal"
    SPIKE_UP    = "spike_up"
    SPIKE_DOWN  = "spike_down"
    RECOVERY    = "recovery"


@dataclass
class RegimeSegment:
    regime: str
    bars: int
    params: Dict[str, Any] = field(default_factory=dict)


# Default regime sequence (can be customised)
DEFAULT_REGIME_SEQUENCE = [
    RegimeSegment(MarketRegime.CHOP,        80,  {"vol": 0.0010, "drift": 0.0}),
    RegimeSegment(MarketRegime.BULL_TREND, 100,  {"vol": 0.0012, "drift": 0.0003}),
    RegimeSegment(MarketRegime.BREAKOUT,    60,  {"vol": 0.0020, "drift": 0.0008}),
    RegimeSegment(MarketRegime.CHOP,        50,  {"vol": 0.0008, "drift": 0.0}),
    RegimeSegment(MarketRegime.FAKE_BREAK,  40,  {"vol": 0.0015, "drift": 0.0002}),
    RegimeSegment(MarketRegime.REVERSAL,    30,  {"vol": 0.0018, "drift": -0.0006}),
    RegimeSegment(MarketRegime.BEAR_TREND,  80,  {"vol": 0.0014, "drift": -0.0004}),
    RegimeSegment(MarketRegime.SPIKE_DOWN,  10,  {"vol": 0.0060, "drift": -0.0020}),
    RegimeSegment(MarketRegime.RECOVERY,    60,  {"vol": 0.0012, "drift": 0.0003}),
    RegimeSegment(MarketRegime.CHOP,        40,  {"vol": 0.0008, "drift": 0.0}),
    RegimeSegment(MarketRegime.BULL_TREND,  80,  {"vol": 0.0010, "drift": 0.0002}),
    RegimeSegment(MarketRegime.SPIKE_UP,    10,  {"vol": 0.0055, "drift": 0.0018}),
    RegimeSegment(MarketRegime.CHOP,        60,  {"vol": 0.0009, "drift": 0.0}),
]


def generate_continuous_ohlcv(
    segments: List[RegimeSegment],
    base_price: float = 45000.0,
    seed: int = 42,
    freq_minutes: int = 5,
) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    Generate a continuous OHLCV DataFrame with regime transitions.
    Returns (df, regime_labels) where regime_labels[i] = regime name for bar i.
    """
    rng = np.random.default_rng(seed)
    prices = [base_price]
    volumes = []
    regimes = []

    for seg in segments:
        drift = seg.params.get("drift", 0.0)
        vol   = seg.params.get("vol",   0.0012)
        for i in range(seg.bars):
            ret = drift + rng.normal(0, vol)
            # Add mean reversion in chop regimes
            if seg.regime == MarketRegime.CHOP:
                ret += -0.05 * (prices[-1] - base_price) / base_price
            prices.append(prices[-1] * (1 + ret))
            base_vol = 400 if seg.regime in (MarketRegime.BREAKOUT, MarketRegime.SPIKE_UP, MarketRegime.SPIKE_DOWN) else 150
            volumes.append(float(rng.uniform(base_vol * 0.7, base_vol * 1.4)))
            regimes.append(seg.regime)

    n = len(regimes)
    close_arr = np.array(prices[1:])
    spread = close_arr * 0.0008
    high_arr   = close_arr + rng.uniform(0, spread, n)
    low_arr    = close_arr - rng.uniform(0, spread * 0.8, n)
    open_arr   = np.maximum(low_arr, close_arr - rng.normal(0, spread / 2, n))

    start = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    ts = pd.date_range(start, periods=n, freq=f"{freq_minutes}min", tz="UTC")

    df = pd.DataFrame({
        "timestamp": ts,
        "open":   open_arr,
        "high":   high_arr,
        "low":    low_arr,
        "close":  close_arr,
        "volume": np.array(volumes),
    })

    regime_labels = [{"bar": i, "regime": r} for i, r in enumerate(regimes)]
    return df, regime_labels


def _resample_to_higher_tf(df5m: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """Resample 5m OHLCV into a higher timeframe."""
    df = df5m.set_index("timestamp")
    rule = f"{target_minutes}min"
    agg = df.resample(rule, closed="left", label="left").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    agg = agg.reset_index()
    return agg


def _build_frames_from_window(
    df_all: pd.DataFrame,
    bar_idx: int,
    window_5m: int = 300,
    window_15m: int = 100,
    window_1h: int = 50,
) -> Dict[str, Any]:
    """Build the frame dict that ScenarioRunner expects from a rolling window."""
    end = bar_idx + 1
    start = max(0, end - window_5m)
    df5m = df_all.iloc[start:end].copy().reset_index(drop=True)

    df15m = _resample_to_higher_tf(df5m, 15)
    if len(df15m) > window_15m:
        df15m = df15m.iloc[-window_15m:].reset_index(drop=True)

    df1h = _resample_to_higher_tf(df5m, 60)
    if len(df1h) > window_1h:
        df1h = df1h.iloc[-window_1h:].reset_index(drop=True)

    # Funding rate: constant small positive
    n_fund = min(len(df1h), 50)
    ts_fund = pd.date_range(df5m["timestamp"].iloc[0], periods=n_fund, freq="1h", tz="UTC")
    df_fund = pd.DataFrame({
        "timestamp":    ts_fund,
        "funding_rate": np.full(n_fund, 0.0001),
    })

    return {
        "v43_df5m":      df5m,
        "v43_df15m":     df15m,
        "v43_df1h":      df1h,
        "v43_df_funding": df_fund,
        "v43_df_oi":     pd.DataFrame(),
        "v43_df_mark":   df5m.copy(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Paper Trade State Machine
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PaperTrade:
    trade_id:    str
    bar_idx:     int
    timestamp:   datetime
    direction:   str           # LONG | SHORT
    entry_price: float
    position_size: float       # fraction of equity (e.g. 0.05)
    stop_loss:   float
    take_profit: float
    reason_codes: List[str]
    regime_at_entry: str

    exit_bar_idx:  Optional[int]   = None
    exit_price:    Optional[float] = None
    exit_reason:   Optional[str]   = None
    exit_ts:       Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def pnl_pct(self) -> float:
        if self.exit_price is None or self.entry_price <= 0:
            return 0.0
        if self.direction == "LONG":
            return (self.exit_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.exit_price) / self.entry_price

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id":       self.trade_id,
            "bar_idx":        self.bar_idx,
            "timestamp":      self.timestamp.isoformat(),
            "direction":      self.direction,
            "entry_price":    round(self.entry_price, 2),
            "position_size":  round(self.position_size, 4),
            "stop_loss":      round(self.stop_loss, 2),
            "take_profit":    round(self.take_profit, 2),
            "regime_at_entry": self.regime_at_entry,
            "reason_codes":   self.reason_codes,
            "exit_bar_idx":   self.exit_bar_idx,
            "exit_price":     round(self.exit_price, 2) if self.exit_price else None,
            "exit_reason":    self.exit_reason,
            "exit_ts":        self.exit_ts.isoformat() if self.exit_ts else None,
            "pnl_pct":        round(self.pnl_pct() * 100, 4),
        }


class PaperPortfolio:
    """Simulates paper trading with position management."""

    def __init__(self, initial_equity: float = 20_000.0,
                 stop_loss_pct: float = 0.0025,
                 take_profit_pct: float = 0.015,
                 max_hold_bars: int = 48,   # ~4h at 5m bars
                 leverage: int = 3):
        self.equity           = initial_equity
        self.initial_equity   = initial_equity
        self.stop_loss_pct    = stop_loss_pct
        self.take_profit_pct  = take_profit_pct
        self.max_hold_bars    = max_hold_bars
        self.leverage         = leverage

        self.open_trade:  Optional[PaperTrade] = None
        self.closed_trades: List[PaperTrade]   = []
        self._trade_count = 0

    # ── entry ──────────────────────────────────────────────────────────────
    def try_open(
        self,
        bar_idx: int,
        ts: datetime,
        price: float,
        signal: str,
        position_size_frac: float,
        reason_codes: List[str],
        regime: str,
    ) -> Optional[PaperTrade]:
        if self.open_trade is not None:
            return None  # already in a trade
        if signal not in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
            return None

        direction = "LONG" if signal in ("BUY", "STRONG_BUY") else "SHORT"
        size_frac  = max(0.01, min(0.50, position_size_frac))

        if direction == "LONG":
            sl = price * (1 - self.stop_loss_pct)
            tp = price * (1 + self.take_profit_pct)
        else:
            sl = price * (1 + self.stop_loss_pct)
            tp = price * (1 - self.take_profit_pct)

        self._trade_count += 1
        trade = PaperTrade(
            trade_id      = f"T{self._trade_count:04d}",
            bar_idx       = bar_idx,
            timestamp     = ts,
            direction     = direction,
            entry_price   = price,
            position_size = size_frac,
            stop_loss     = sl,
            take_profit   = tp,
            reason_codes  = reason_codes,
            regime_at_entry = regime,
        )
        self.open_trade = trade
        return trade

    # ── price update / exit check ──────────────────────────────────────────
    def update(
        self, bar_idx: int, ts: datetime, high: float, low: float, close: float,
        current_signal: Optional[str] = None,
    ) -> Optional[str]:
        """Return exit_reason if a position was closed, else None."""
        if self.open_trade is None:
            return None

        t = self.open_trade
        bars_held = bar_idx - t.bar_idx
        exit_reason = None
        exit_price  = close

        if t.direction == "LONG":
            if low <= t.stop_loss:
                exit_reason = "stop_loss"
                exit_price  = t.stop_loss
            elif high >= t.take_profit:
                exit_reason = "take_profit"
                exit_price  = t.take_profit
        else:  # SHORT
            if high >= t.stop_loss:
                exit_reason = "stop_loss"
                exit_price  = t.stop_loss
            elif low <= t.take_profit:
                exit_reason = "take_profit"
                exit_price  = t.take_profit

        # Signal flip exit
        if exit_reason is None and current_signal:
            flip = (t.direction == "LONG"  and current_signal in ("SELL", "STRONG_SELL"))
            flip = flip or (t.direction == "SHORT" and current_signal in ("BUY",  "STRONG_BUY"))
            if flip:
                exit_reason = "signal_flip"

        # Max hold time exit
        if exit_reason is None and bars_held >= self.max_hold_bars:
            exit_reason = "max_hold"

        if exit_reason:
            t.exit_bar_idx = bar_idx
            t.exit_price   = exit_price
            t.exit_reason  = exit_reason
            t.exit_ts      = ts

            # Update equity (simplified: position_size * leverage * pnl)
            leverage_gain  = self.leverage * t.pnl_pct() * t.position_size
            self.equity   *= (1 + leverage_gain)

            self.closed_trades.append(t)
            self.open_trade = None
            return exit_reason

        return None

    # ── portfolio state for pipeline injection ─────────────────────────────
    def portfolio_state(self) -> Dict[str, Any]:
        positions = {}
        if self.open_trade:
            t = self.open_trade
            positions[t.trade_id] = {
                "status":   "open",
                "side":     t.direction,
                "size":     t.position_size,
                "notional": t.position_size * self.equity,
            }
        return {
            "portfolio_value":     self.equity,
            "portfolio_equity_usd": self.equity,
            "positions":           positions,
        }

    # ── statistics ─────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        ct = self.closed_trades
        if not ct:
            return {"total_trades": 0}
        pnls = [t.pnl_pct() for t in ct]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        by_reason = {}
        for t in ct:
            by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1
        by_regime = {}
        for t in ct:
            by_regime[t.regime_at_entry] = by_regime.get(t.regime_at_entry, 0) + 1
        return {
            "total_trades":     len(ct),
            "win_rate_pct":     round(100 * len(wins) / len(ct), 1),
            "avg_pnl_pct":      round(100 * float(np.mean(pnls)), 4),
            "total_return_pct": round(100 * (self.equity - self.initial_equity) / self.initial_equity, 2),
            "max_win_pct":      round(100 * max(pnls), 4),
            "max_loss_pct":     round(100 * min(pnls), 4),
            "profit_factor":    round(sum(wins) / max(abs(sum(losses)), 1e-9), 3),
            "exit_reasons":     by_reason,
            "entries_per_regime": by_regime,
            "final_equity":     round(self.equity, 2),
            "initial_equity":   round(self.initial_equity, 2),
        }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — Component Metric Collectors
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BarRecord:
    """Full record for one simulation bar / pipeline run."""
    bar_idx:   int
    timestamp: str
    price:     float
    regime:    str

    # pipeline timing (ms)
    pipeline_ms: float = 0.0
    pipeline_error: Optional[str] = None

    # ml_inference
    ml_ok: bool = False
    ml_expected_return: float = 0.0
    ml_threshold: float = 0.005
    ml_raw_long:  bool  = False
    ml_raw_short: bool  = False

    # multi_horizon
    mh_ok: bool = False
    mh_alignment: float = 0.0
    mh_regime: str = ""

    # market_structure
    struct_ok: bool = False
    struct_type: str = ""
    struct_trend: str = ""

    # thesis
    thesis_ok: bool = False
    thesis_direction: str = ""
    thesis_signal: str = ""
    thesis_confidence: float = 0.0
    thesis_type: str = ""

    # ml_gates
    gates_ok: bool = False
    gates_final_long:  bool = False
    gates_final_short: bool = False
    gates_reject: str = ""

    # trade_scorer
    scorer_ok: bool = False
    score: float = 0.0
    score_passed: bool = False
    score_components: Dict[str, float] = field(default_factory=dict)

    # policy_engine
    policy_ok: bool = False
    policy_signal: str = ""
    policy_confidence: float = 0.0
    policy_position_size: float = 0.0
    policy_reason_codes: List[str] = field(default_factory=list)

    # portfolio_guard
    guard_ok: bool = False
    guard_action: str = ""
    guard_heat_ratio: float = 0.0
    guard_allowed_size: float = 0.0

    # final decision
    final_signal: str = "HOLD"
    final_execute: bool = False

    # trade events
    trade_opened: Optional[str] = None
    trade_closed: Optional[str] = None
    trade_exit_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        # flatten score_components
        d["score_components_json"] = json.dumps(d.pop("score_components", {}))
        d["policy_reason_codes_json"] = json.dumps(d.pop("policy_reason_codes", []))
        return d


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — Simulation Engine
# ═══════════════════════════════════════════════════════════════════════════

class ContinuousSimulator:
    """
    Feeds rolling windows of synthetic candles through the full JackSparrow
    pipeline and collects comprehensive per-bar metrics.
    """

    def __init__(
        self,
        symbol: str = "BTCUSD",
        metadata_path: Optional[Path] = None,
        warmup_bars: int = 300,      # bars needed before pipeline starts
        window_5m: int = 300,
    ):
        self.symbol       = symbol
        self.warmup_bars  = warmup_bars
        self.window_5m    = window_5m
        self.metadata_path = metadata_path or (
            _REPO / "agent/model_storage/JackSparrow_v43_models_BTCUSD/metadata_v43.json"
        )
        self._node = None
        self.records: List[BarRecord] = []
        self.errors:  List[Dict]      = []
        self.warnings: List[Dict]     = []

    # ── lazy model load ────────────────────────────────────────────────────
    def _load_model(self) -> None:
        if self._node is not None:
            return
        from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
        print(f"  Loading model from {self.metadata_path} …", flush=True)
        self._node = JackSparrowV43Node.from_metadata_path(self.metadata_path)
        print(f"  Model loaded (forward_bars={self._node.training_forward_bars})", flush=True)

    # ── single bar pipeline ────────────────────────────────────────────────
    async def _run_pipeline(
        self,
        frames: Dict[str, Any],
        bar_record: BarRecord,
        portfolio_state: Dict[str, Any],
    ) -> None:
        """Run full 9-layer pipeline, writing results into bar_record."""
        from agent.testing.scenario_runner import ScenarioRunner
        from agent.testing.scenario_assertions import evaluate

        scenario = {
            "scenario_name":  f"bar_{bar_record.bar_idx}",
            "description":    f"Continuous sim bar {bar_record.bar_idx}",
            "expected":       {},
            "frames":         frames,
            "portfolio_state": portfolio_state,
        }

        # Build runner (reuses cached model node)
        runner = _get_runner(self.symbol, self.metadata_path)
        runner._node = self._node

        t0 = time.perf_counter()
        trace = await runner.run(scenario)
        bar_record.pipeline_ms = (time.perf_counter() - t0) * 1000.0

        if trace.error:
            bar_record.pipeline_error = trace.error
            self.errors.append({
                "bar": bar_record.bar_idx,
                "stage": "pipeline",
                "error": trace.error,
            })
            return

        # ── extract per-layer metrics ──────────────────────────────────────
        for lyr in trace.layers:
            if not lyr.ok:
                self.errors.append({
                    "bar":   bar_record.bar_idx,
                    "stage": lyr.name,
                    "error": lyr.error,
                    "ms":    round(lyr.duration_ms, 2),
                })

        def _out(name: str) -> Dict[str, Any]:
            l = trace.layer(name)
            return l.output if l and l.ok else {}

        # ml_inference
        ml = _out("ml_inference")
        bar_record.ml_ok           = bool(trace.layer("ml_inference") and trace.layer("ml_inference").ok)
        bar_record.ml_expected_return = float(ml.get("expected_return", 0.0) or 0.0)
        bar_record.ml_threshold    = float(ml.get("threshold", 0.005) or 0.005)
        bar_record.ml_raw_long     = bool(ml.get("raw_long", False))
        bar_record.ml_raw_short    = bool(ml.get("raw_short", False))

        # multi_horizon
        mh = _out("multi_horizon")
        bar_record.mh_ok        = bool(trace.layer("multi_horizon") and trace.layer("multi_horizon").ok)
        bar_record.mh_alignment = float(mh.get("alignment_score", 0.0) or 0.0)
        bar_record.mh_regime    = str(mh.get("regime", "") or "")

        # market_structure
        st = _out("market_structure")
        bar_record.struct_ok    = bool(trace.layer("market_structure") and trace.layer("market_structure").ok)
        bar_record.struct_type  = str(st.get("market_type", "") or "")
        bar_record.struct_trend = str(st.get("trend", "") or "")

        # thesis
        th = _out("thesis")
        bar_record.thesis_ok         = bool(trace.layer("thesis") and trace.layer("thesis").ok)
        bar_record.thesis_direction  = str(th.get("direction", "") or "")
        bar_record.thesis_signal     = str(th.get("signal", "") or "")
        bar_record.thesis_confidence = float(th.get("confidence", 0.0) or 0.0)
        bar_record.thesis_type       = str(th.get("thesis_type", "") or "")

        # ml_gates
        g = _out("ml_gates")
        bar_record.gates_ok          = bool(trace.layer("ml_gates") and trace.layer("ml_gates").ok)
        bar_record.gates_final_long  = bool(g.get("final_long", False))
        bar_record.gates_final_short = bool(g.get("final_short", False))
        bar_record.gates_reject      = str(g.get("gate_reject", "") or "")

        # trade_scorer
        sc = _out("trade_scorer")
        bar_record.scorer_ok       = bool(trace.layer("trade_scorer") and trace.layer("trade_scorer").ok)
        bar_record.score           = float(sc.get("score", 0.0) or 0.0)
        bar_record.score_passed    = bool(sc.get("passed", False))
        bar_record.score_components = {k: float(v) for k, v in (sc.get("components") or {}).items()}

        # policy_engine
        po = _out("policy_engine")
        bar_record.policy_ok            = bool(trace.layer("policy_engine") and trace.layer("policy_engine").ok)
        bar_record.policy_signal        = str(po.get("signal", "HOLD") or "HOLD")
        bar_record.policy_confidence    = float(po.get("confidence", 0.0) or 0.0)
        bar_record.policy_position_size = float(po.get("position_size", 0.0) or 0.0)
        bar_record.policy_reason_codes  = list(po.get("reason_codes", []) or [])

        # portfolio_guard
        pg = _out("portfolio_guard")
        bar_record.guard_ok           = bool(trace.layer("portfolio_guard") and trace.layer("portfolio_guard").ok)
        bar_record.guard_action       = str(pg.get("action", "") or "")
        bar_record.guard_heat_ratio   = float(pg.get("heat_ratio", 0.0) or 0.0)
        bar_record.guard_allowed_size = float(pg.get("allowed_size_fraction", 0.0) or 0.0)

        # final_decision
        fd = _out("final_decision")
        bar_record.final_signal  = str(fd.get("signal", "HOLD") or "HOLD")
        bar_record.final_execute = bool(fd.get("execute", False))

    # ── main simulation loop ───────────────────────────────────────────────
    async def run(
        self,
        segments: List[RegimeSegment],
        base_price: float = 45000.0,
        seed: int = 42,
    ) -> Dict[str, Any]:
        print("\n[SIM] Generating synthetic market data …", flush=True)
        df_all, regime_labels = generate_continuous_ohlcv(
            segments, base_price=base_price, seed=seed
        )
        total_bars = len(df_all)
        print(f"[SIM] {total_bars} synthetic bars generated "
              f"({total_bars * 5 / 60:.1f}h of simulated market time)", flush=True)

        # Load model once
        self._load_model()

        portfolio = PaperPortfolio(
            initial_equity   = 20_000.0,
            stop_loss_pct    = 0.0025,
            take_profit_pct  = 0.015,
            max_hold_bars    = 48,
            leverage         = 3,
        )

        regime_map = {r["bar"]: r["regime"] for r in regime_labels}
        active_bars = range(self.warmup_bars, total_bars)
        print(f"[SIM] Pipeline will run on bars {self.warmup_bars}–{total_bars - 1} "
              f"({len(active_bars)} pipeline steps)", flush=True)
        print("[SIM] Running simulation …", flush=True)

        t_sim_start = time.perf_counter()

        for i, bar_idx in enumerate(active_bars):
            row = df_all.iloc[bar_idx]
            price     = float(row["close"])
            high_px   = float(row["high"])
            low_px    = float(row["low"])
            ts        = row["timestamp"].to_pydatetime()
            regime    = regime_map.get(bar_idx, "unknown")

            bar = BarRecord(
                bar_idx   = bar_idx,
                timestamp = ts.isoformat(),
                price     = round(price, 2),
                regime    = regime,
            )

            # 1. Update portfolio (check SL/TP on current bar before pipeline)
            exit_reason = portfolio.update(
                bar_idx, ts, high_px, low_px, price,
                current_signal=None   # don't flip yet; we'll do it after pipeline
            )
            if exit_reason:
                bar.trade_closed    = portfolio.closed_trades[-1].trade_id
                bar.trade_exit_reason = exit_reason

            # 2. Build frames
            frames = _build_frames_from_window(
                df_all, bar_idx,
                window_5m  = self.window_5m,
                window_15m = 100,
                window_1h  = 50,
            )

            # 3. Run full pipeline
            try:
                await self._run_pipeline(frames, bar, portfolio.portfolio_state())
            except Exception as exc:
                bar.pipeline_error = f"{type(exc).__name__}: {exc}"
                self.errors.append({
                    "bar": bar_idx,
                    "stage": "pipeline_toplevel",
                    "error": bar.pipeline_error,
                    "tb": traceback.format_exc()[-500:],
                })

            # 4. Signal-flip exit (after pipeline)
            if portfolio.open_trade and bar.final_signal in ("BUY","STRONG_BUY","SELL","STRONG_SELL"):
                exit_reason2 = portfolio.update(
                    bar_idx, ts, high_px, low_px, price,
                    current_signal=bar.final_signal,
                )
                if exit_reason2 == "signal_flip":
                    bar.trade_closed     = portfolio.closed_trades[-1].trade_id
                    bar.trade_exit_reason = "signal_flip"

            # 5. Try open new trade if pipeline says execute
            if bar.final_execute and portfolio.open_trade is None:
                sig  = bar.final_signal
                size = bar.guard_allowed_size if bar.guard_allowed_size > 0 else bar.policy_position_size
                size = max(0.01, size)
                t = portfolio.try_open(
                    bar_idx, ts, price, sig, size,
                    reason_codes=bar.policy_reason_codes[:6],
                    regime=regime,
                )
                if t:
                    bar.trade_opened = t.trade_id

            self.records.append(bar)

            # Progress indicator
            if (i + 1) % 50 == 0 or i == len(active_bars) - 1:
                pct = 100.0 * (i + 1) / len(active_bars)
                elapsed = time.perf_counter() - t_sim_start
                eta     = elapsed / max(i + 1, 1) * (len(active_bars) - i - 1)
                print(f"  [{pct:5.1f}%] bar {bar_idx:4d}/{total_bars - 1}  "
                      f"regime={regime:<16} "
                      f"signal={bar.final_signal:<10} "
                      f"equity=${portfolio.equity:,.0f}  "
                      f"ETA {eta:.0f}s", flush=True)

        # close any still-open position at end
        if portfolio.open_trade:
            last_bar = df_all.iloc[-1]
            last_ts  = last_bar["timestamp"].to_pydatetime()
            portfolio.open_trade.exit_bar_idx = len(df_all) - 1
            portfolio.open_trade.exit_price   = float(last_bar["close"])
            portfolio.open_trade.exit_reason  = "sim_end"
            portfolio.open_trade.exit_ts      = last_ts
            portfolio.equity *= 1 + portfolio.leverage * portfolio.open_trade.pnl_pct() * portfolio.open_trade.position_size
            portfolio.closed_trades.append(portfolio.open_trade)
            portfolio.open_trade = None

        sim_seconds = time.perf_counter() - t_sim_start

        # ── aggregate metrics ──────────────────────────────────────────────
        results = self._build_results(
            df_all, regime_labels, portfolio, sim_seconds, total_bars
        )
        return results

    # ── results aggregation ────────────────────────────────────────────────
    def _build_results(
        self,
        df_all: pd.DataFrame,
        regime_labels: List[Dict],
        portfolio: PaperPortfolio,
        sim_seconds: float,
        total_bars: int,
    ) -> Dict[str, Any]:
        recs = self.records
        n = len(recs)
        if n == 0:
            return {}

        # Component health
        def _rate(pred) -> float:
            vals = [pred(r) for r in recs]
            return round(100 * sum(vals) / max(len(vals), 1), 1)

        layer_health = {
            "ml_inference":    _rate(lambda r: r.ml_ok),
            "multi_horizon":   _rate(lambda r: r.mh_ok),
            "market_structure":_rate(lambda r: r.struct_ok),
            "thesis":          _rate(lambda r: r.thesis_ok),
            "ml_gates":        _rate(lambda r: r.gates_ok),
            "trade_scorer":    _rate(lambda r: r.scorer_ok),
            "policy_engine":   _rate(lambda r: r.policy_ok),
            "portfolio_guard": _rate(lambda r: r.guard_ok),
        }

        # Signal distribution
        from collections import Counter
        sig_counts = Counter(r.final_signal for r in recs)
        gate_rejects = Counter(r.gates_reject for r in recs if r.gates_reject)
        thesis_directions = Counter(r.thesis_direction for r in recs)
        struct_types = Counter(r.struct_type for r in recs)
        regime_counts = Counter(r.regime for r in recs)

        # Score stats
        scores = [r.score for r in recs if r.scorer_ok]
        ml_returns = [r.ml_expected_return for r in recs if r.ml_ok]
        mh_aligns = [r.mh_alignment for r in recs if r.mh_ok]
        timings = [r.pipeline_ms for r in recs if r.pipeline_ms > 0]

        # Score component averages
        score_comp_agg: Dict[str, List[float]] = {}
        for r in recs:
            for k, v in r.score_components.items():
                score_comp_agg.setdefault(k, []).append(v)
        score_comp_means = {k: round(float(np.mean(v)), 2) for k, v in score_comp_agg.items()}

        # Policy reason code frequencies
        reason_freq: Counter = Counter()
        for r in recs:
            reason_freq.update(r.policy_reason_codes)

        # Per-regime signal analysis
        regime_signals: Dict[str, Counter] = {}
        for r in recs:
            rg = r.regime
            regime_signals.setdefault(rg, Counter())
            regime_signals[rg][r.final_signal] += 1

        # Pipeline errors by stage
        error_by_stage: Counter = Counter()
        for e in self.errors:
            error_by_stage[e["stage"]] += 1

        # Bar-level timeline (compact — only trade events + signal changes)
        price_series = [{"b": r.bar_idx, "p": r.price, "r": r.regime, "s": r.final_signal}
                        for r in recs[::5]]   # every 5 bars to keep compact
        ml_return_series = [{"b": r.bar_idx, "v": round(r.ml_expected_return * 100, 4)}
                            for r in recs[::5] if r.ml_ok]

        return {
            "meta": {
                "symbol":        self.symbol,
                "generated_at":  datetime.now(timezone.utc).isoformat(),
                "total_bars":    total_bars,
                "active_bars":   n,
                "warmup_bars":   self.warmup_bars,
                "sim_seconds":   round(sim_seconds, 2),
                "bars_per_second": round(n / max(sim_seconds, 0.01), 1),
                "simulated_hours": round(total_bars * 5 / 60, 1),
            },
            "layer_health_pct": layer_health,
            "signal_distribution": dict(sig_counts),
            "gate_reject_reasons": dict(gate_rejects),
            "thesis_direction_dist": dict(thesis_directions),
            "struct_type_dist": dict(struct_types),
            "regime_distribution": dict(regime_counts),
            "score_stats": {
                "mean":   round(float(np.mean(scores)), 2) if scores else 0,
                "median": round(float(np.median(scores)), 2) if scores else 0,
                "p75":    round(float(np.percentile(scores, 75)), 2) if scores else 0,
                "p90":    round(float(np.percentile(scores, 90)), 2) if scores else 0,
                "pct_passed": round(100 * sum(1 for r in recs if r.score_passed) / max(n, 1), 1),
            },
            "score_components_mean": score_comp_means,
            "ml_return_stats": {
                "mean":    round(float(np.mean(ml_returns)) * 100, 4) if ml_returns else 0,
                "std":     round(float(np.std(ml_returns))  * 100, 4) if ml_returns else 0,
                "pct_positive": round(100 * sum(1 for v in ml_returns if v > 0) / max(len(ml_returns), 1), 1),
            },
            "mh_alignment_stats": {
                "mean": round(float(np.mean(mh_aligns)), 3) if mh_aligns else 0,
                "std":  round(float(np.std(mh_aligns)), 3)  if mh_aligns else 0,
            },
            "timing_ms": {
                "mean":   round(float(np.mean(timings)), 1) if timings else 0,
                "median": round(float(np.median(timings)), 1) if timings else 0,
                "p95":    round(float(np.percentile(timings, 95)), 1) if timings else 0,
                "max":    round(float(np.max(timings)), 1) if timings else 0,
            },
            "policy_reason_top15": dict(reason_freq.most_common(15)),
            "regime_signals": {k: dict(v) for k, v in regime_signals.items()},
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "error_by_stage": dict(error_by_stage),
            "errors": self.errors[:50],   # cap at 50
            "trade_stats":   portfolio.stats(),
            "closed_trades": [t.to_dict() for t in portfolio.closed_trades],
            # compact time-series for charts
            "price_series":     price_series,
            "ml_return_series": ml_return_series,
            # full bar records (trimmed)
            "bar_records": [r.to_dict() for r in recs],
        }


# Singleton runner pool (one per symbol) to avoid repeated model loads
_runners: Dict[str, Any] = {}

def _get_runner(symbol: str, metadata_path: Path) -> Any:
    from agent.testing.scenario_runner import ScenarioRunner
    key = f"{symbol}:{metadata_path}"
    if key not in _runners:
        _runners[key] = ScenarioRunner(metadata_path=metadata_path, symbol=symbol)
    return _runners[key]


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — HTML Report Generator
# ═══════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JackSparrow v43 – Continuous Simulation Report</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0d1117;--card:#161b22;--border:#30363d;--accent:#58a6ff;
  --green:#3fb950;--red:#f85149;--yellow:#d29922;--purple:#bc8cff;
  --text:#e6edf3;--sub:#8b949e;--font:'Segoe UI',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;line-height:1.5;}
h1{font-size:1.4rem;font-weight:700;color:var(--accent);}
h2{font-size:1rem;font-weight:600;color:var(--text);margin-bottom:8px;}
h3{font-size:.85rem;font-weight:600;color:var(--sub);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em;}
.header{padding:20px 24px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;}
.badge{background:var(--accent);color:#000;padding:2px 8px;border-radius:9px;font-size:.7rem;font-weight:700;}
.grid{display:grid;gap:12px;padding:16px 24px;}
.g2{grid-template-columns:1fr 1fr;}
.g3{grid-template-columns:1fr 1fr 1fr;}
.g4{grid-template-columns:repeat(4,1fr);}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;}
.kpi{text-align:center;}
.kpi .val{font-size:1.8rem;font-weight:700;line-height:1.1;}
.kpi .lbl{font-size:.7rem;color:var(--sub);margin-top:2px;}
.green{color:var(--green)!important;} .red{color:var(--red)!important;} .yellow{color:var(--yellow)!important;}
.bar-row{display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:.78rem;}
.bar-bg{flex:1;background:#21262d;border-radius:3px;height:8px;overflow:hidden;}
.bar-fill{height:100%;border-radius:3px;}
.bar-pct{width:38px;text-align:right;color:var(--sub);}
table{width:100%;border-collapse:collapse;font-size:.76rem;}
th{background:#1c2128;padding:6px 10px;text-align:left;color:var(--sub);font-weight:500;border-bottom:1px solid var(--border);}
td{padding:5px 10px;border-bottom:1px solid #21262d;}
tr:last-child td{border-bottom:0;}
.sig-buy{color:var(--green);font-weight:600;}
.sig-sell{color:var(--red);font-weight:600;}
.sig-hold{color:var(--sub);}
.err{color:var(--red);background:#1a0a0a;padding:8px 10px;border-radius:4px;font-size:.75rem;font-family:monospace;margin-bottom:4px;}
canvas{max-height:240px;}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.chip{display:inline-block;padding:1px 7px;border-radius:9px;font-size:.68rem;font-weight:600;background:#21262d;}
.chip.ok{background:#0d2810;color:var(--green);}
.chip.warn{background:#2d2008;color:var(--yellow);}
.chip.err{background:#2d080a;color:var(--red);}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🏴‍☠️ JackSparrow v43 · Continuous Simulation Report</h1>
    <div style="margin-top:4px;color:var(--sub);font-size:.8rem;">
      Symbol: <strong>__SYMBOL__</strong> &nbsp;·&nbsp;
      Generated: <strong>__DATE__</strong> &nbsp;·&nbsp;
      Simulated: <strong>__SIM_HOURS__h</strong> of market time compressed to <strong>__SIM_SECS__s</strong>
    </div>
  </div>
  <span class="badge">v43</span>
</div>

<!-- KPI row -->
<div class="grid g4" style="padding-top:16px;">
  <div class="card kpi">
    <div class="val">__TOTAL_BARS__</div>
    <div class="lbl">Pipeline Runs</div>
  </div>
  <div class="card kpi">
    <div class="val __TRADE_COLOR__">__TOTAL_TRADES__</div>
    <div class="lbl">Total Trades</div>
  </div>
  <div class="card kpi">
    <div class="val __WIN_COLOR__">__WIN_RATE__%</div>
    <div class="lbl">Win Rate</div>
  </div>
  <div class="card kpi">
    <div class="val __PNL_COLOR__">__RETURN_PCT__%</div>
    <div class="lbl">Total Return (simulated)</div>
  </div>
</div>

<!-- Charts row -->
<div class="grid g2">
  <div class="card">
    <h2>Price + Signals</h2>
    <canvas id="priceChart"></canvas>
  </div>
  <div class="card">
    <h2>ML Expected Return (% vs threshold)</h2>
    <canvas id="mlChart"></canvas>
  </div>
</div>

<!-- Layer health + signal dist -->
<div class="grid g2">
  <div class="card">
    <h2>Pipeline Layer Health</h2>
    <canvas id="healthChart"></canvas>
  </div>
  <div class="card">
    <h2>Signal Distribution by Regime</h2>
    <canvas id="regimeChart"></canvas>
  </div>
</div>

<!-- Gate rejects + score stats -->
<div class="grid g2">
  <div class="card">
    <h2>Gate Rejection Breakdown</h2>
    <div id="gateRejects"></div>
  </div>
  <div class="card">
    <h2>Trade Score Components (Avg)</h2>
    <canvas id="scoreChart"></canvas>
  </div>
</div>

<!-- Trade log -->
<div class="grid" style="grid-template-columns:1fr;">
  <div class="card">
    <h2>Trade Log</h2>
    <table id="tradeTable">
      <thead><tr>
        <th>#</th><th>Direction</th><th>Regime</th>
        <th>Entry</th><th>Exit</th><th>Exit Reason</th>
        <th>P&amp;L %</th><th>Bars Held</th>
      </tr></thead>
      <tbody id="tradeTbody"></tbody>
    </table>
  </div>
</div>

<!-- Detailed stats -->
<div class="grid g2">
  <div class="card">
    <h2>Component Statistics</h2>
    <table>
      <tr><th>Metric</th><th>Value</th></tr>
      __COMP_ROWS__
    </table>
  </div>
  <div class="card">
    <h2>Top Policy Reason Codes</h2>
    <div id="reasonCodes"></div>
  </div>
</div>

<!-- Errors -->
<div class="grid" style="grid-template-columns:1fr;">
  <div class="card">
    <h2>Pipeline Errors &amp; Warnings <span class="chip __ERR_CLASS__">__ERR_COUNT__</span></h2>
    <div id="errorList"></div>
  </div>
</div>

<div style="padding:16px 24px;color:var(--sub);font-size:.72rem;">
  JackSparrow v43 Continuous Simulation · Synthetic data only · Not financial advice
</div>

<script>
const DATA = __JSON_DATA__;

// ── price + signal chart ─────────────────────────────────────────────────
(function(){
  const ps = DATA.price_series || [];
  const labels = ps.map(d=>d.b);
  const prices = ps.map(d=>d.p);
  const regimes = ps.map(d=>d.r);
  const signals = ps.map(d=>d.s);
  const buyPts  = ps.map((d,i)=>d.s==='BUY'||d.s==='STRONG_BUY'?d.p:null);
  const sellPts = ps.map((d,i)=>d.s==='SELL'||d.s==='STRONG_SELL'?d.p:null);

  // Regime colour bands
  const regimeColors = {
    chop:'rgba(100,100,100,0.08)', bull_trend:'rgba(0,200,100,0.08)',
    bear_trend:'rgba(240,50,50,0.08)', breakout:'rgba(80,180,255,0.12)',
    fake_breakout:'rgba(255,200,0,0.10)', reversal:'rgba(255,100,50,0.10)',
    spike_up:'rgba(80,255,160,0.15)', spike_down:'rgba(255,60,60,0.15)',
    recovery:'rgba(120,200,255,0.09)'
  };

  new Chart(document.getElementById('priceChart'),{
    type:'line',
    data:{
      labels,
      datasets:[
        {label:'Price',data:prices,borderColor:'#58a6ff',borderWidth:1.5,pointRadius:0,tension:0.1,fill:false,order:1},
        {label:'BUY',data:buyPts,borderColor:'transparent',backgroundColor:'#3fb950',pointRadius:4,pointStyle:'triangle',showLine:false,order:0},
        {label:'SELL',data:sellPts,borderColor:'transparent',backgroundColor:'#f85149',pointRadius:4,pointStyle:'triangle',showLine:false,rotation:180,order:0},
      ]
    },
    options:{animation:false,responsive:true,maintainAspectRatio:true,
      plugins:{legend:{display:true,labels:{boxWidth:10,font:{size:10}}},tooltip:{mode:'index',intersect:false}},
      scales:{x:{display:true,ticks:{maxTicksLimit:10,font:{size:9}},title:{display:true,text:'Bar Index',font:{size:9}}},
              y:{display:true,ticks:{font:{size:9}}}}}
  });
})();

// ── ml return chart ─────────────────────────────────────────────────────
(function(){
  const ms = DATA.ml_return_series || [];
  const labels = ms.map(d=>d.b);
  const vals   = ms.map(d=>d.v);
  const thr    = (DATA.bar_records[0]?.ml_threshold||0.005)*100;
  new Chart(document.getElementById('mlChart'),{
    type:'line',
    data:{
      labels,
      datasets:[
        {label:'Expected Return %',data:vals,borderColor:'#bc8cff',borderWidth:1.2,pointRadius:0,fill:false},
        {label:'Threshold',data:Array(labels.length).fill(thr),borderColor:'rgba(248,81,73,0.5)',borderWidth:1,borderDash:[4,4],pointRadius:0,fill:false},
        {label:'-Threshold',data:Array(labels.length).fill(-thr),borderColor:'rgba(63,185,80,0.5)',borderWidth:1,borderDash:[4,4],pointRadius:0,fill:false},
      ]
    },
    options:{animation:false,responsive:true,maintainAspectRatio:true,
      plugins:{legend:{labels:{boxWidth:10,font:{size:10}}}},
      scales:{x:{ticks:{maxTicksLimit:10,font:{size:9}}},y:{ticks:{font:{size:9}}}}}
  });
})();

// ── layer health bar chart ──────────────────────────────────────────────
(function(){
  const lh = DATA.layer_health_pct||{};
  const labels = Object.keys(lh);
  const vals   = Object.values(lh);
  new Chart(document.getElementById('healthChart'),{
    type:'bar',
    data:{
      labels,
      datasets:[{label:'Success %',data:vals,
        backgroundColor:vals.map(v=>v>=95?'#3fb95066':v>=80?'#d2992266':'#f8514966'),
        borderColor:vals.map(v=>v>=95?'#3fb950':v>=80?'#d29922':'#f85149'),
        borderWidth:1}]
    },
    options:{animation:false,indexAxis:'y',responsive:true,maintainAspectRatio:true,
      plugins:{legend:{display:false}},
      scales:{x:{min:0,max:100,ticks:{callback:v=>v+'%',font:{size:9}}},
              y:{ticks:{font:{size:9}}}}}
  });
})();

// ── regime signal chart ──────────────────────────────────────────────────
(function(){
  const rs = DATA.regime_signals||{};
  const regimes = Object.keys(rs);
  const signals = ['BUY','STRONG_BUY','SELL','STRONG_SELL','HOLD'];
  const colors  = ['#3fb950','#2ea043','#f85149','#da3633','#666'];
  new Chart(document.getElementById('regimeChart'),{
    type:'bar',
    data:{
      labels:regimes,
      datasets:signals.map((s,i)=>({
        label:s, data:regimes.map(r=>(rs[r]||{})[s]||0),
        backgroundColor:colors[i]+'88', borderColor:colors[i], borderWidth:1
      }))
    },
    options:{animation:false,responsive:true,maintainAspectRatio:true,
      plugins:{legend:{labels:{boxWidth:10,font:{size:10}}}},
      scales:{x:{stacked:true,ticks:{font:{size:8}}},y:{stacked:true,ticks:{font:{size:9}}}}}
  });
})();

// ── gate rejects ─────────────────────────────────────────────────────────
(function(){
  const gr = DATA.gate_reject_reasons||{};
  const items = Object.entries(gr).sort((a,b)=>b[1]-a[1]);
  const total = items.reduce((s,[,v])=>s+v,0);
  const el = document.getElementById('gateRejects');
  if(!items.length){el.innerHTML='<span style="color:var(--sub)">No gate rejections recorded</span>';return;}
  el.innerHTML = items.slice(0,10).map(([k,v])=>{
    const pct = total>0?Math.round(100*v/total):0;
    return `<div class="bar-row">
      <span style="min-width:160px;color:var(--text)">${k}</span>
      <div class="bar-bg"><div class="bar-fill" style="width:${pct}%;background:var(--yellow);"></div></div>
      <span class="bar-pct">${v}</span>
    </div>`;
  }).join('');
})();

// ── score components chart ───────────────────────────────────────────────
(function(){
  const sc = DATA.score_components_mean||{};
  const labels = Object.keys(sc);
  const vals   = Object.values(sc);
  new Chart(document.getElementById('scoreChart'),{
    type:'bar',
    data:{labels,datasets:[{label:'Avg Points',data:vals,backgroundColor:'#58a6ff88',borderColor:'#58a6ff',borderWidth:1}]},
    options:{animation:false,responsive:true,maintainAspectRatio:true,
      plugins:{legend:{display:false}},
      scales:{x:{ticks:{font:{size:9}}},y:{ticks:{font:{size:9}}}}}
  });
})();

// ── trade table ──────────────────────────────────────────────────────────
(function(){
  const trades = DATA.closed_trades||[];
  const tbody = document.getElementById('tradeTbody');
  tbody.innerHTML = trades.map((t,i)=>{
    const pnl = t.pnl_pct||0;
    const cls = pnl>0?'green':pnl<0?'red':'';
    const dir = t.direction==='LONG'?'▲ LONG':'▼ SHORT';
    const dirCls = t.direction==='LONG'?'sig-buy':'sig-sell';
    const held = (t.exit_bar_idx||t.bar_idx) - t.bar_idx;
    return `<tr>
      <td>${i+1}</td>
      <td class="${dirCls}">${dir}</td>
      <td>${t.regime_at_entry||'—'}</td>
      <td>$${(t.entry_price||0).toLocaleString()}</td>
      <td>${t.exit_price?'$'+(t.exit_price||0).toLocaleString():'open'}</td>
      <td>${t.exit_reason||'—'}</td>
      <td class="${cls}">${pnl>0?'+':''}${(pnl||0).toFixed(3)}%</td>
      <td>${held}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--sub)">No closed trades</td></tr>';
})();

// ── reason codes ─────────────────────────────────────────────────────────
(function(){
  const rc = DATA.policy_reason_top15||{};
  const items = Object.entries(rc).sort((a,b)=>b[1]-a[1]).slice(0,12);
  const total = items.reduce((s,[,v])=>s+v,0);
  const el = document.getElementById('reasonCodes');
  if(!items.length){el.innerHTML='<span style="color:var(--sub)">None</span>';return;}
  el.innerHTML = items.map(([k,v])=>{
    const pct = total>0?Math.round(100*v/total):0;
    return `<div class="bar-row">
      <span style="min-width:240px;color:var(--text);font-size:.75rem">${k}</span>
      <div class="bar-bg"><div class="bar-fill" style="width:${pct}%;background:var(--purple);"></div></div>
      <span class="bar-pct">${v}</span>
    </div>`;
  }).join('');
})();

// ── errors ───────────────────────────────────────────────────────────────
(function(){
  const errs = DATA.errors||[];
  const el = document.getElementById('errorList');
  if(!errs.length){el.innerHTML='<span style="color:var(--green)">✓ No pipeline errors recorded</span>';return;}
  el.innerHTML = errs.slice(0,20).map(e=>
    `<div class="err">[bar ${e.bar}] <strong>${e.stage}</strong>: ${e.error}</div>`
  ).join('');
})();
</script>
</body>
</html>
"""


def build_html_report(results: Dict[str, Any]) -> str:
    meta   = results.get("meta", {})
    ts     = results.get("trade_stats", {})
    n      = meta.get("active_bars", 0)
    trades = ts.get("total_trades", 0)
    wr     = ts.get("win_rate_pct", 0)
    ret    = ts.get("total_return_pct", 0)
    errs   = results.get("error_count", 0)

    win_color  = "green" if wr   >= 50 else "red"
    pnl_color  = "green" if ret  > 0   else "red"
    err_class  = "ok"    if errs == 0  else "err"
    trade_color = "green" if trades > 0 else "yellow"

    # Component stats table rows
    lh  = results.get("layer_health_pct", {})
    sc  = results.get("score_stats", {})
    ml  = results.get("ml_return_stats", {})
    mh  = results.get("mh_alignment_stats", {})
    tm  = results.get("timing_ms", {})

    def row(label, val, suffix="", cls=""):
        style = f' class="{cls}"' if cls else ""
        return f"<tr><td>{label}</td><td{style}>{val}{suffix}</td></tr>"

    comp_rows = "\n".join([
        row("Active pipeline bars", n),
        row("Avg pipeline latency", tm.get("mean","—"), " ms"),
        row("P95 pipeline latency", tm.get("p95","—"), " ms"),
        row("Max pipeline latency", tm.get("max","—"), " ms"),
        row("Score: mean", sc.get("mean","—")),
        row("Score: median", sc.get("median","—")),
        row("Score: % passed (≥70)", f"{sc.get('pct_passed','—')}%"),
        row("ML return: mean", f"{ml.get('mean','—')}%"),
        row("ML return: std",  f"{ml.get('std','—')}%"),
        row("ML pct positive", f"{ml.get('pct_positive','—')}%"),
        row("MH alignment mean", mh.get("mean","—")),
        row("Total pipeline errors", errs, "", "red" if errs else "green"),
        row("Total trades", ts.get("total_trades","—")),
        row("Win rate",  f"{ts.get('win_rate_pct','—')}%", "", win_color),
        row("Profit factor", ts.get("profit_factor","—")),
        row("Avg P&L per trade", f"{ts.get('avg_pnl_pct','—')}%"),
        row("Max win", f"{ts.get('max_win_pct','—')}%", "", "green"),
        row("Max loss", f"{ts.get('max_loss_pct','—')}%", "", "red"),
        row("Final equity", f"${ts.get('final_equity',0):,.0f}"),
        row("Total return",  f"{ret}%", "", pnl_color),
    ])

    html = HTML_TEMPLATE
    html = html.replace("__SYMBOL__", meta.get("symbol","BTCUSD"))
    html = html.replace("__DATE__",   meta.get("generated_at","")[:19])
    html = html.replace("__SIM_HOURS__", str(meta.get("simulated_hours","?")))
    html = html.replace("__SIM_SECS__",  str(meta.get("sim_seconds","?")))
    html = html.replace("__TOTAL_BARS__", str(n))
    html = html.replace("__TOTAL_TRADES__", str(trades))
    html = html.replace("__TRADE_COLOR__",  trade_color)
    html = html.replace("__WIN_RATE__",  str(wr))
    html = html.replace("__WIN_COLOR__", win_color)
    html = html.replace("__RETURN_PCT__", str(ret))
    html = html.replace("__PNL_COLOR__",  pnl_color)
    html = html.replace("__COMP_ROWS__", comp_rows)
    html = html.replace("__ERR_COUNT__", str(errs))
    html = html.replace("__ERR_CLASS__", err_class)
    html = html.replace("__JSON_DATA__", json.dumps(results, default=str))
    return html


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="JackSparrow v43 Continuous Simulation")
    p.add_argument("--symbol",   default="BTCUSD")
    p.add_argument("--seed",     type=int, default=42)
    p.add_argument("--base-price", type=float, default=45000.0)
    p.add_argument("--warmup",   type=int, default=300,
                   help="Warmup bars before pipeline starts (default 300 = 5m × 300 = 25h)")
    p.add_argument("--no-html",  action="store_true", help="Skip HTML report generation")
    p.add_argument("--out-dir",  default=".", help="Directory for output files")
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  JackSparrow v43 · CONTINUOUS SIMULATION")
    print("=" * 70)
    print(f"  Symbol:       {args.symbol}")
    print(f"  Base price:   ${args.base_price:,.0f}")
    print(f"  Seed:         {args.seed}")
    print(f"  Warmup bars:  {args.warmup}")

    total_segs = sum(s.bars for s in DEFAULT_REGIME_SEQUENCE)
    print(f"  Total bars:   {total_segs}  ({total_segs*5/60:.1f}h simulated)")
    print(f"  Active bars:  {total_segs - args.warmup}  (pipeline runs)")
    print()

    sim = ContinuousSimulator(
        symbol       = args.symbol,
        warmup_bars  = args.warmup,
    )

    results = await sim.run(
        segments   = DEFAULT_REGIME_SEQUENCE,
        base_price = args.base_price,
        seed       = args.seed,
    )

    # ── write JSON ─────────────────────────────────────────────────────────
    ts_str  = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"sim_results_{ts_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[OUT] JSON results  -> {json_path}")

    # ── write HTML ─────────────────────────────────────────────────────────
    if not args.no_html:
        html_path = out_dir / f"sim_report_{ts_str}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(build_html_report(results))
        print(f"[OUT] HTML report   -> {html_path}")

    # ── print summary ───────────────────────────────────────────────────────
    meta = results.get("meta", {})
    ts_  = results.get("trade_stats", {})
    lh   = results.get("layer_health_pct", {})
    print()
    print("─" * 60)
    print("  SIMULATION SUMMARY")
    print("─" * 60)
    print(f"  Simulated market time : {meta.get('simulated_hours','?')}h "
          f"({meta.get('active_bars','?')} pipeline steps)")
    print(f"  Wall-clock time       : {meta.get('sim_seconds','?'):.1f}s "
          f"({meta.get('bars_per_second','?'):.0f} bars/s)")
    print()
    print("  LAYER HEALTH:")
    for name, pct in lh.items():
        icon = "✓" if pct >= 95 else "⚠" if pct >= 80 else "✗"
        print(f"    {icon} {name:<22} {pct:5.1f}%")
    print()
    print("  SIGNAL DISTRIBUTION:")
    for sig, cnt in sorted(results.get("signal_distribution", {}).items()):
        bar_ = "█" * min(30, cnt // 2)
        print(f"    {sig:<14} {cnt:4d}  {bar_}")
    print()
    print("  GATE REJECTS (top 5):")
    for reason, cnt in list(results.get("gate_reject_reasons", {}).items())[:5]:
        print(f"    {reason:<32} {cnt}")
    print()
    print("  TRADE STATISTICS:")
    for k, v in ts_.items():
        if not isinstance(v, dict):
            print(f"    {k:<28} {v}")
    print()
    print(f"  Pipeline errors: {results.get('error_count', 0)}")
    if results.get("errors"):
        for e in results["errors"][:3]:
            print(f"    [bar {e['bar']}] {e['stage']}: {e['error'][:80]}")
    print("─" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
