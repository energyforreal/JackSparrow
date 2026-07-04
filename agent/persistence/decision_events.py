"""Event-driven trade decision timeline persistence."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_EVENT_DIR = Path("data/decision_events")


@dataclass
class DecisionEvent:
    """One append-only decision timeline record."""

    event_id: str
    position_id: str
    symbol: str
    event_type: str
    captured_at: str
    sequence_num: int = 0
    reasoning_chain_id: Optional[str] = None
    bar_index: Optional[int] = None
    caused_by: List[str] = field(default_factory=list)
    delta: Optional[Dict[str, Any]] = None
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "position_id": self.position_id,
            "reasoning_chain_id": self.reasoning_chain_id,
            "symbol": self.symbol,
            "event_type": self.event_type,
            "bar_index": self.bar_index,
            "sequence_num": self.sequence_num,
            "captured_at": self.captured_at,
            "caused_by": list(self.caused_by),
            "delta": dict(self.delta) if isinstance(self.delta, dict) else None,
            "payload": dict(self.payload) if isinstance(self.payload, dict) else None,
        }


def _canonical_event_hash(event_type: str, delta: Any, payload: Any) -> str:
    blob = json.dumps(
        {"event_type": event_type, "delta": delta, "payload": payload},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _events_enabled() -> bool:
    return bool(getattr(settings, "trade_decision_events_enabled", False))


class DecisionEventEmitter:
    """In-memory emitter with dedupe and causality tracking per position."""

    def __init__(self) -> None:
        self._sequence: Dict[str, int] = {}
        self._last_hash: Dict[str, str] = {}
        self._recent_event_ids: Dict[str, List[str]] = {}
        self._buffers: Dict[str, List[DecisionEvent]] = {}

    def reset_position(self, position_id: str) -> None:
        """Clear in-memory state for a position (tests)."""
        self._sequence.pop(position_id, None)
        self._last_hash.pop(position_id, None)
        self._recent_event_ids.pop(position_id, None)
        self._buffers.pop(position_id, None)

    def buffer_for_position(self, position_id: str) -> List[DecisionEvent]:
        return list(self._buffers.get(position_id) or [])

    def emit_if_changed(
        self,
        *,
        position_id: str,
        symbol: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        delta: Optional[Dict[str, Any]] = None,
        caused_by: Optional[List[str]] = None,
        reasoning_chain_id: Optional[str] = None,
        bar_index: Optional[int] = None,
        captured_at: Optional[datetime] = None,
    ) -> Optional[DecisionEvent]:
        """Emit event when payload/delta differs from last event of same type."""
        if not _events_enabled():
            return None
        if not position_id or not symbol:
            return None

        dedupe_key = f"{position_id}:{event_type}"
        content_hash = _canonical_event_hash(event_type, delta, payload)
        if self._last_hash.get(dedupe_key) == content_hash:
            return None

        seq = self._sequence.get(position_id, 0) + 1
        self._sequence[position_id] = seq
        self._last_hash[dedupe_key] = content_hash

        ts = captured_at or datetime.now(timezone.utc)
        caused = list(caused_by or [])
        if not caused:
            recent = self._recent_event_ids.get(position_id) or []
            if recent:
                caused = [recent[-1]]

        event = DecisionEvent(
            event_id=str(uuid.uuid4()),
            position_id=str(position_id),
            reasoning_chain_id=reasoning_chain_id,
            symbol=str(symbol).strip().upper(),
            event_type=str(event_type),
            bar_index=bar_index,
            sequence_num=seq,
            captured_at=ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            caused_by=caused,
            delta=dict(delta) if isinstance(delta, dict) else None,
            payload=dict(payload) if isinstance(payload, dict) else None,
        )

        buf = self._buffers.setdefault(position_id, [])
        buf.append(event)
        max_events = int(
            getattr(settings, "trade_decision_events_max_per_position", 500) or 500
        )
        if len(buf) > max_events:
            self._buffers[position_id] = buf[-max_events:]

        recent_ids = self._recent_event_ids.setdefault(position_id, [])
        recent_ids.append(event.event_id)
        if len(recent_ids) > 50:
            self._recent_event_ids[position_id] = recent_ids[-50:]

        self._schedule_persist(event)
        return event

    def _schedule_persist(self, event: DecisionEvent) -> None:
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(_persist_event(event), name="decision_event_write")
        except RuntimeError:
            _append_jsonl_fallback(event)

    def build_causality_graph(self, position_id: str) -> Dict[str, Any]:
        """Materialize small causality summary from buffered events."""
        events = self._buffers.get(position_id) or []
        nodes = [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "sequence_num": e.sequence_num,
                "caused_by": list(e.caused_by),
            }
            for e in events
        ]
        edges = [
            {"from": parent, "to": e.event_id}
            for e in events
            for parent in e.caused_by
        ]
        return {
            "position_id": position_id,
            "event_count": len(events),
            "nodes": nodes[-50:],
            "edges": edges[-100:],
        }


decision_event_emitter = DecisionEventEmitter()


def _append_jsonl_fallback(event: DecisionEvent) -> None:
    try:
        _EVENT_DIR.mkdir(parents=True, exist_ok=True)
        path = _EVENT_DIR / f"{event.position_id}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), default=str) + "\n")
    except OSError as exc:
        logger.warning(
            "decision_event_jsonl_failed",
            position_id=event.position_id,
            error=str(exc),
        )


async def _persist_event(event: DecisionEvent) -> None:
    db_url = getattr(settings, "database_url", None)
    if not db_url:
        _append_jsonl_fallback(event)
        return
    try:
        from agent.persistence.db_writes import persist_decision_event_async

        captured = datetime.fromisoformat(event.captured_at.replace("Z", "+00:00"))
        await persist_decision_event_async(
            db_url,
            event_id=event.event_id,
            position_id=event.position_id,
            reasoning_chain_id=event.reasoning_chain_id,
            symbol=event.symbol,
            event_type=event.event_type,
            bar_index=event.bar_index,
            sequence_num=event.sequence_num,
            captured_at=captured,
            caused_by=event.caused_by,
            delta=event.delta,
            payload=event.payload,
        )
    except Exception as exc:
        logger.warning(
            "decision_event_persist_failed",
            event_id=event.event_id,
            error=str(exc),
        )
        _append_jsonl_fallback(event)


def emit_tle_cycle_events(
    *,
    position_id: str,
    symbol: str,
    reasoning_chain_id: Optional[str],
    monitoring_record: Dict[str, Any],
    verdict: Any,
    prior_regime: Optional[str] = None,
    prior_structure: Optional[str] = None,
    prior_conviction: Optional[float] = None,
) -> None:
    """Emit decision events from one TLE monitoring cycle."""
    if not _events_enabled():
        return

    ms = monitoring_record.get("market_state")
    if isinstance(ms, dict):
        regime = str(ms.get("regime") or "")
        if regime and prior_regime and regime != prior_regime:
            decision_event_emitter.emit_if_changed(
                position_id=position_id,
                symbol=symbol,
                event_type="regime_shift",
                reasoning_chain_id=reasoning_chain_id,
                bar_index=monitoring_record.get("bar_index"),
                delta={"field": "regime", "from": prior_regime, "to": regime},
                payload={"market_state": ms},
            )

    structure = monitoring_record.get("structure_state")
    if structure and prior_structure and structure != prior_structure:
        decision_event_emitter.emit_if_changed(
            position_id=position_id,
            symbol=symbol,
            event_type="structure_transition",
            reasoning_chain_id=reasoning_chain_id,
            bar_index=monitoring_record.get("bar_index"),
            delta={
                "field": "structure_state",
                "from": prior_structure,
                "to": structure,
            },
            payload={"transition": monitoring_record.get("structure_transition")},
        )

    conviction_now = getattr(verdict, "conviction_now", None)
    min_delta = float(
        getattr(settings, "trade_decision_event_min_conviction_delta", 0.05) or 0.05
    )
    if conviction_now is not None and prior_conviction is not None:
        try:
            delta_val = float(conviction_now) - float(prior_conviction)
            if abs(delta_val) >= min_delta:
                decision_event_emitter.emit_if_changed(
                    position_id=position_id,
                    symbol=symbol,
                    event_type="conviction_change",
                    reasoning_chain_id=reasoning_chain_id,
                    bar_index=monitoring_record.get("bar_index"),
                    delta={
                        "field": "conviction",
                        "from": prior_conviction,
                        "to": conviction_now,
                        "magnitude": delta_val,
                    },
                )
        except (TypeError, ValueError):
            pass

    continuation = monitoring_record.get("continuation")
    if isinstance(continuation, dict):
        for code in continuation.get("invalidation_codes") or []:
            decision_event_emitter.emit_if_changed(
                position_id=position_id,
                symbol=symbol,
                event_type="continuation_invalidation",
                reasoning_chain_id=reasoning_chain_id,
                bar_index=monitoring_record.get("bar_index"),
                payload={"code": str(code)},
                delta={"field": "invalidation", "to": str(code)},
            )

    if hasattr(verdict, "to_dict"):
        vdict = verdict.to_dict()
    elif isinstance(verdict, dict):
        vdict = verdict
    else:
        vdict = {}
    decision_event_emitter.emit_if_changed(
        position_id=position_id,
        symbol=symbol,
        event_type="tle_verdict",
        reasoning_chain_id=reasoning_chain_id,
        bar_index=monitoring_record.get("bar_index"),
        payload=vdict,
    )


def extract_denorm_from_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Pull denormalized trade_outcomes columns from close metadata."""
    meta = metadata if isinstance(metadata, dict) else {}
    dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
    sys_ctx = meta.get("system_context") if isinstance(meta.get("system_context"), dict) else {}
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
    mstate = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    assessment = (
        meta.get("post_trade_assessment")
        if isinstance(meta.get("post_trade_assessment"), dict)
        else {}
    )
    eq = dc.get("entry_quality") if isinstance(dc.get("entry_quality"), dict) else {}
    timing = meta.get("execution_timing") if isinstance(meta.get("execution_timing"), dict) else {}
    outcome = meta.get("outcome") if isinstance(meta.get("outcome"), dict) else {}
    excursions = outcome.get("excursions") if isinstance(outcome.get("excursions"), dict) else {}

    out: Dict[str, Any] = {
        "config_hash": sys_ctx.get("config_hash"),
        "setup_type": gates.get("setup_type"),
        "regime": mstate.get("regime"),
        "root_cause": assessment.get("root_cause"),
        "entry_quality_score": eq.get("quality_score"),
        "mfe_pct": excursions.get("mfe_pct"),
        "mae_pct": excursions.get("mae_pct"),
        "slippage_bps_entry": timing.get("execution_slippage_bps_entry"),
        "decision_event_count": meta.get("decision_event_count"),
    }
    return {k: v for k, v in out.items() if v is not None}
