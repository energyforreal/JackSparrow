"""Market FSM — lifecycle decision engine for rule-based trading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.signal_vocabulary import is_entry_signal, normalize_signal
from agent.intelligence.market_types import (
    FSMDecision,
    MarketStateSnapshot,
    StructuralGateResult,
)

logger = structlog.get_logger()

_FSM_STATES = (
    "Watching",
    "TrendDeveloping",
    "SetupForming",
    "EntryReady",
    "PositionActive",
    "Managing",
    "ExitReady",
)

_DEFAULT_FSM_DIR = Path("data/market_fsm")


class MarketFSM:
    """Finite state machine driven by structural evidence and narrative."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or _DEFAULT_FSM_DIR
        self._state: Dict[str, str] = {}

    def _path(self, symbol: str) -> Path:
        return self._base_dir / f"{str(symbol).strip().upper()}.json"

    def load_state(self, symbol: str) -> str:
        sym = str(symbol).strip().upper()
        if sym in self._state:
            return self._state[sym]
        path = self._path(sym)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._state[sym] = str(raw.get("fsm_state") or "Watching")
                return self._state[sym]
            except (json.JSONDecodeError, OSError):
                pass
        self._state[sym] = "Watching"
        return "Watching"

    def persist_state(self, symbol: str, fsm_state: str, extra: Optional[Dict[str, Any]] = None) -> None:
        sym = str(symbol).strip().upper()
        self._state[sym] = fsm_state
        path = self._path(sym)
        payload = {"fsm_state": fsm_state, **(extra or {})}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.warning("market_fsm_persist_failed", symbol=sym, error=str(exc))

    def _thesis_health(self, snapshot: MarketStateSnapshot) -> str:
        if snapshot.momentum == "decreasing" and snapshot.trend_strength == "weak":
            return "broken"
        if snapshot.momentum == "decreasing":
            return "weakening"
        return "healthy"

    def _position_lifecycle(self, fsm_state: str) -> str:
        mapping = {
            "Watching": "watching",
            "TrendDeveloping": "watching",
            "SetupForming": "watching",
            "EntryReady": "entry_ready",
            "PositionActive": "managing",
            "Managing": "managing",
            "ExitReady": "exit_ready",
        }
        return mapping.get(fsm_state, "watching")

    def _transition(
        self,
        current: str,
        snapshot: MarketStateSnapshot,
        gates: StructuralGateResult,
        narrative_tail: List[Dict[str, Any]],
        has_open_position: bool,
    ) -> str:
        recent = {e.get("event_type") for e in narrative_tail[-10:]}

        if has_open_position:
            if current in ("Watching", "TrendDeveloping", "SetupForming", "EntryReady"):
                return "PositionActive"
            health = self._thesis_health(snapshot)
            if health in ("weakening", "broken") or "trend_exhaustion" in recent:
                return "ExitReady"
            return "Managing"

        if current == "Watching":
            if snapshot.trend != "neutral" and snapshot.momentum in ("increasing", "flat"):
                return "TrendDeveloping"
            return "Watching"

        if current == "TrendDeveloping":
            if "pullback_ends" in recent or snapshot.volatility == "compressing":
                return "SetupForming"
            if snapshot.trend == "neutral":
                return "Watching"
            return "TrendDeveloping"

        if current == "SetupForming":
            if gates.trade_allowed and (
                "breakout_confirmed" in recent
                or "retest_successful" in recent
                or gates.setup_type == "trend_continuation"
            ):
                return "EntryReady"
            if snapshot.breakout_status == "failed" or snapshot.trend == "neutral":
                return "Watching"
            return "SetupForming"

        if current == "EntryReady":
            if not gates.trade_allowed:
                return "SetupForming"
            return "EntryReady"

        if current in ("PositionActive", "Managing", "ExitReady"):
            if not has_open_position:
                return "Watching"
            return current

        return current

    def evaluate(
        self,
        *,
        snapshot: MarketStateSnapshot,
        gates: StructuralGateResult,
        narrative_tail: List[Dict[str, Any]],
        has_open_position: bool = False,
    ) -> FSMDecision:
        """Update FSM and return lifecycle decision."""
        sym = snapshot.symbol
        current = self.load_state(sym)
        new_state = self._transition(
            current, snapshot, gates, narrative_tail, has_open_position
        )
        if new_state != current:
            logger.info(
                "market_fsm_transition",
                symbol=sym,
                from_state=current,
                to_state=new_state,
                bar_index=snapshot.bar_index,
            )
        self.persist_state(sym, new_state, {"bar_index": snapshot.bar_index})

        entry_signal = "HOLD"
        exit_signal = False
        abstention: Optional[str] = None
        health = self._thesis_health(snapshot)

        if new_state == "EntryReady" and gates.trade_allowed and not has_open_position:
            bias = normalize_signal(snapshot.direction_bias)
            if is_entry_signal(bias):
                entry_signal = bias
            elif snapshot.trend == "bullish":
                entry_signal = "LONG"
            elif snapshot.trend == "bearish":
                entry_signal = "SHORT"
            else:
                abstention = "fsm_no_direction_bias"
        elif new_state == "ExitReady" and has_open_position:
            exit_signal = True
            entry_signal = "HOLD"
            abstention = "fsm_exit_ready"
        elif has_open_position:
            entry_signal = "HOLD"
            abstention = "fsm_position_active"
        else:
            abstention = f"fsm_state_{new_state}"

        decision = FSMDecision(
            fsm_state=new_state,
            entry_signal=entry_signal,
            exit_signal=exit_signal,
            abstention_reason=abstention,
            narrative_tail=list(narrative_tail[-5:]),
            thesis_health=health,
            position_lifecycle=self._position_lifecycle(new_state),
        )
        return decision

    def on_position_opened(self, symbol: str) -> None:
        sym = str(symbol).strip().upper()
        self.persist_state(sym, "PositionActive")

    def on_position_closed(self, symbol: str) -> None:
        sym = str(symbol).strip().upper()
        self.persist_state(sym, "Watching")


market_fsm = MarketFSM()
