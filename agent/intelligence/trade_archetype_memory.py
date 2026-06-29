"""Trade archetype memory — structured pattern storage without ML embeddings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_DEFAULT_DIR = Path("data/trade_archetypes")


@dataclass
class TradeArchetype:
    """Completed trade archetype record."""

    symbol: str
    setup_type: str
    regime: str
    narrative_pattern_hash: str
    gate_snapshot: Dict[str, bool] = field(default_factory=dict)
    fsm_path: List[str] = field(default_factory=list)
    outcome: str = "unknown"
    duration_bars: int = 0
    pnl_pct: float = 0.0
    closed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "setup_type": self.setup_type,
            "regime": self.regime,
            "narrative_pattern_hash": self.narrative_pattern_hash,
            "gate_snapshot": dict(self.gate_snapshot),
            "fsm_path": list(self.fsm_path),
            "outcome": self.outcome,
            "duration_bars": self.duration_bars,
            "pnl_pct": self.pnl_pct,
            "closed_at": self.closed_at,
        }


def narrative_pattern_hash(narrative_tail: List[Dict[str, Any]]) -> str:
    """Hash recent narrative event types for similarity matching."""
    types = [str(e.get("event_type") or "") for e in narrative_tail[-8:]]
    payload = "|".join(types)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class TradeArchetypeMemory:
    """Persist and query trade archetypes by structured similarity."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base_dir = base_dir or _DEFAULT_DIR

    def _path(self, symbol: str) -> Path:
        return self._base_dir / f"{str(symbol).strip().upper()}.jsonl"

    def record_close(
        self,
        *,
        symbol: str,
        setup_type: str,
        regime: str,
        narrative_tail: List[Dict[str, Any]],
        gate_snapshot: Dict[str, bool],
        fsm_path: List[str],
        outcome: str,
        duration_bars: int = 0,
        pnl_pct: float = 0.0,
    ) -> TradeArchetype:
        """Append archetype on trade close."""
        arch = TradeArchetype(
            symbol=str(symbol).strip().upper(),
            setup_type=setup_type,
            regime=regime,
            narrative_pattern_hash=narrative_pattern_hash(narrative_tail),
            gate_snapshot=dict(gate_snapshot),
            fsm_path=list(fsm_path),
            outcome=outcome,
            duration_bars=duration_bars,
            pnl_pct=pnl_pct,
            closed_at=datetime.now(timezone.utc).isoformat(),
        )
        path = self._path(symbol)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(arch.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("trade_archetype_persist_failed", symbol=symbol, error=str(exc))
        return arch

    def load_all(self, symbol: str) -> List[TradeArchetype]:
        path = self._path(symbol)
        out: List[TradeArchetype] = []
        if not path.exists():
            return out
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                out.append(
                    TradeArchetype(
                        symbol=str(raw.get("symbol") or ""),
                        setup_type=str(raw.get("setup_type") or ""),
                        regime=str(raw.get("regime") or ""),
                        narrative_pattern_hash=str(raw.get("narrative_pattern_hash") or ""),
                        gate_snapshot=dict(raw.get("gate_snapshot") or {}),
                        fsm_path=list(raw.get("fsm_path") or []),
                        outcome=str(raw.get("outcome") or ""),
                        duration_bars=int(raw.get("duration_bars") or 0),
                        pnl_pct=float(raw.get("pnl_pct") or 0.0),
                        closed_at=str(raw.get("closed_at") or ""),
                    )
                )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("trade_archetype_load_failed", symbol=symbol, error=str(exc))
        return out

    def similar_setups(
        self,
        symbol: str,
        *,
        setup_type: str,
        regime: str,
        narrative_tail: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Find similar past setups and win rate (shadow sizing hints)."""
        pattern = narrative_pattern_hash(narrative_tail)
        records = self.load_all(symbol)
        similar = [
            r
            for r in records
            if r.setup_type == setup_type
            and (r.regime == regime or r.narrative_pattern_hash == pattern)
        ]
        if not similar:
            return {"count": 0, "win_rate": None, "pattern_hash": pattern}
        wins = sum(1 for r in similar if r.outcome == "win" or r.pnl_pct > 0)
        win_rate = wins / len(similar)
        result = {
            "count": len(similar),
            "win_rate": round(win_rate, 3),
            "pattern_hash": pattern,
        }
        shadow = bool(getattr(settings, "archetype_memory_shadow", True))
        logger.info(
            "trade_archetype_similarity",
            symbol=symbol,
            setup_type=setup_type,
            shadow_only=shadow,
            **result,
        )
        return result


trade_archetype_memory = TradeArchetypeMemory()
