"""Market Narrative Engine — evolving sequence of market events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.intelligence.market_types import MarketStateSnapshot, NarrativeEvent

logger = structlog.get_logger()

_DEFAULT_NARRATIVE_DIR = Path("data/market_narrative")
_MAX_EVENTS = 200
_MAX_TAIL = 20


class MarketNarrativeEngine:
    """Append-only market event timeline derived from understanding deltas."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or _DEFAULT_NARRATIVE_DIR
        self._cache: Dict[str, List[NarrativeEvent]] = {}
        self._prev_snapshot: Dict[str, MarketStateSnapshot] = {}
        self._resistance_test_count: Dict[str, int] = {}
        self._support_test_count: Dict[str, int] = {}

    def _path(self, symbol: str) -> Path:
        sym = str(symbol).strip().upper()
        return self._base_dir / f"{sym}.jsonl"

    def load(self, symbol: str) -> List[NarrativeEvent]:
        sym = str(symbol).strip().upper()
        if sym in self._cache:
            return list(self._cache[sym])
        events: List[NarrativeEvent] = []
        path = self._path(sym)
        if path.exists():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    events.append(
                        NarrativeEvent(
                            event_type=str(raw.get("event_type") or ""),
                            timestamp=str(raw.get("timestamp") or ""),
                            bar_index=int(raw.get("bar_index") or 0),
                            detail=dict(raw.get("detail") or {}),
                            count=raw.get("count"),
                        )
                    )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("market_narrative_load_failed", symbol=sym, error=str(exc))
        self._cache[sym] = events[-_MAX_EVENTS:]
        return list(self._cache[sym])

    def persist(self, symbol: str, events: List[NarrativeEvent]) -> None:
        sym = str(symbol).strip().upper()
        trimmed = events[-_MAX_EVENTS:]
        self._cache[sym] = trimmed
        path = self._path(sym)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fh:
                for ev in trimmed:
                    fh.write(json.dumps(ev.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("market_narrative_persist_failed", symbol=sym, error=str(exc))

    def _emit(
        self,
        events: List[NarrativeEvent],
        *,
        event_type: str,
        bar_index: int,
        detail: Optional[Dict[str, Any]] = None,
        count: Optional[int] = None,
    ) -> NarrativeEvent:
        ev = NarrativeEvent(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            bar_index=bar_index,
            detail=dict(detail or {}),
            count=count,
        )
        events.append(ev)
        return ev

    def update_from_snapshot(
        self,
        snapshot: MarketStateSnapshot,
        *,
        features: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[NarrativeEvent], List[Dict[str, Any]]]:
        """Detect narrative events from snapshot delta; return new events and tail."""
        sym = snapshot.symbol
        prev = self._prev_snapshot.get(sym)
        events = self.load(sym)
        new_events: List[NarrativeEvent] = []
        feats = features or {}

        if prev is None:
            if snapshot.trend in ("bullish", "bearish"):
                et = "uptrend_begins" if snapshot.trend == "bullish" else "downtrend_begins"
                new_events.append(
                    self._emit(events, event_type=et, bar_index=snapshot.bar_index)
                )
        else:
            if prev.trend != snapshot.trend:
                if snapshot.trend == "bullish":
                    new_events.append(
                        self._emit(
                            events,
                            event_type="uptrend_begins",
                            bar_index=snapshot.bar_index,
                        )
                    )
                elif snapshot.trend == "bearish":
                    new_events.append(
                        self._emit(
                            events,
                            event_type="downtrend_begins",
                            bar_index=snapshot.bar_index,
                        )
                    )
                new_events.append(
                    self._emit(
                        events,
                        event_type="regime_transition",
                        bar_index=snapshot.bar_index,
                        detail={"from": prev.regime, "to": snapshot.regime},
                    )
                )

            if prev.momentum == "increasing" and snapshot.momentum == "decreasing":
                new_events.append(
                    self._emit(
                        events,
                        event_type="pullback_starts",
                        bar_index=snapshot.bar_index,
                    )
                )
            if prev.momentum == "decreasing" and snapshot.momentum in (
                "increasing",
                "flat",
            ):
                new_events.append(
                    self._emit(
                        events,
                        event_type="pullback_ends",
                        bar_index=snapshot.bar_index,
                    )
                )

            if snapshot.volatility == "compressing" and prev.volatility != "compressing":
                new_events.append(
                    self._emit(
                        events,
                        event_type="compression_detected",
                        bar_index=snapshot.bar_index,
                    )
                )
            if snapshot.volatility == "expanding" and prev.volatility != "expanding":
                new_events.append(
                    self._emit(
                        events,
                        event_type="volatility_expansion",
                        bar_index=snapshot.bar_index,
                    )
                )

            if snapshot.breakout_status == "forming" and prev.breakout_status == "none":
                new_events.append(
                    self._emit(
                        events,
                        event_type="breakout_attempt",
                        bar_index=snapshot.bar_index,
                    )
                )
            if snapshot.breakout_status == "confirmed" and prev.breakout_status != "confirmed":
                new_events.append(
                    self._emit(
                        events,
                        event_type="breakout_confirmed",
                        bar_index=snapshot.bar_index,
                    )
                )
            if snapshot.breakout_status == "failed" and prev.breakout_status != "failed":
                new_events.append(
                    self._emit(
                        events,
                        event_type="breakout_failed",
                        bar_index=snapshot.bar_index,
                    )
                )

            if snapshot.retest_status == "successful" and prev.retest_status != "successful":
                new_events.append(
                    self._emit(
                        events,
                        event_type="retest_successful",
                        bar_index=snapshot.bar_index,
                    )
                )
            if snapshot.retest_status == "failed":
                new_events.append(
                    self._emit(
                        events,
                        event_type="retest_failed",
                        bar_index=snapshot.bar_index,
                    )
                )

            dist_upper = float(feats.get("dist_upper_pct", 0) or 0)
            if 0 < dist_upper < 0.003:
                self._resistance_test_count[sym] = self._resistance_test_count.get(sym, 0) + 1
                cnt = self._resistance_test_count[sym]
                new_events.append(
                    self._emit(
                        events,
                        event_type="resistance_tested",
                        bar_index=snapshot.bar_index,
                        count=cnt,
                    )
                )
            dist_lower = float(feats.get("dist_lower_pct", 0) or 0)
            if 0 < dist_lower < 0.003:
                self._support_test_count[sym] = self._support_test_count.get(sym, 0) + 1
                cnt = self._support_test_count[sym]
                new_events.append(
                    self._emit(
                        events,
                        event_type="support_tested",
                        bar_index=snapshot.bar_index,
                        count=cnt,
                    )
                )

            if snapshot.trend_strength == "weak" and prev.trend_strength in (
                "moderate",
                "strong",
            ):
                new_events.append(
                    self._emit(
                        events,
                        event_type="trend_exhaustion",
                        bar_index=snapshot.bar_index,
                    )
                )

        self._prev_snapshot[sym] = snapshot
        if new_events:
            self.persist(sym, events)
            for ev in new_events:
                logger.info(
                    "market_narrative_event",
                    symbol=sym,
                    event_type=ev.event_type,
                    bar_index=ev.bar_index,
                    count=ev.count,
                )

        tail = [e.to_dict() for e in events[-_MAX_TAIL:]]
        return new_events, tail

    def resistance_test_count(self, symbol: str) -> int:
        return int(self._resistance_test_count.get(str(symbol).strip().upper(), 0))


market_narrative_engine = MarketNarrativeEngine()
