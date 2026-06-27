"""Persistent market state trajectory (trend drift, failed breakouts, liquidity)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.evidence_types import EvidenceBundle, MarketForecastBundle

logger = structlog.get_logger()

_DEFAULT_STATE_DIR = Path("data/market_state")


@dataclass
class MarketStateTrajectory:
    """Rolling trajectory fields persisted across decision cycles."""

    symbol: str
    bar_index: int = 0
    trend_strength_delta: float = 0.0
    failed_breakout_count: int = 0
    liquidity_drift: float = 0.0
    regime_history: List[str] = field(default_factory=list)
    last_evidence_summary: Dict[str, float] = field(default_factory=dict)
    last_forecast: Optional[Dict[str, Any]] = None
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "trend_strength_delta": self.trend_strength_delta,
            "failed_breakout_count": self.failed_breakout_count,
            "liquidity_drift": self.liquidity_drift,
            "regime_history": list(self.regime_history)[-20:],
            "last_evidence_summary": dict(self.last_evidence_summary),
            "last_forecast": self.last_forecast,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MarketStateTrajectory":
        return cls(
            symbol=str(raw.get("symbol") or ""),
            bar_index=int(raw.get("bar_index") or 0),
            trend_strength_delta=float(raw.get("trend_strength_delta") or 0.0),
            failed_breakout_count=int(raw.get("failed_breakout_count") or 0),
            liquidity_drift=float(raw.get("liquidity_drift") or 0.0),
            regime_history=list(raw.get("regime_history") or []),
            last_evidence_summary=dict(raw.get("last_evidence_summary") or {}),
            last_forecast=raw.get("last_forecast"),
            updated_at=str(raw.get("updated_at") or ""),
        )


class MarketStateEngine:
    """Update and persist market understanding trajectory."""

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self._dir = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR
        self._cache: Dict[str, MarketStateTrajectory] = {}

    def _path(self, symbol: str) -> Path:
        sym = str(symbol or "").strip().upper()
        return self._dir / f"{sym}.json"

    def load(self, symbol: str) -> MarketStateTrajectory:
        sym = str(symbol or "").strip().upper()
        if sym in self._cache:
            return self._cache[sym]
        path = self._path(sym)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                traj = MarketStateTrajectory.from_dict(raw)
                self._cache[sym] = traj
                return traj
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                logger.warning("market_state_load_failed", symbol=sym, error=str(exc))
        traj = MarketStateTrajectory(symbol=sym)
        self._cache[sym] = traj
        return traj

    def persist(self, symbol: str, trajectory: MarketStateTrajectory) -> None:
        sym = str(symbol or "").strip().upper()
        trajectory.updated_at = datetime.now(timezone.utc).isoformat()
        self._cache[sym] = trajectory
        path = self._path(sym)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(trajectory.to_dict(), indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("market_state_persist_failed", symbol=sym, error=str(exc))

    async def persist_redis(self, symbol: str, trajectory: MarketStateTrajectory) -> None:
        """Optional Redis mirror when configured."""
        if not bool(getattr(settings, "market_state_redis_enabled", False)):
            return
        try:
            from agent.core.redis_config_cache import get_redis_client

            client = get_redis_client()
            if client is None:
                return
            key = f"market_state:{str(symbol).strip().upper()}"
            trajectory.updated_at = datetime.now(timezone.utc).isoformat()
            await client.set(key, json.dumps(trajectory.to_dict()), ex=86400 * 7)
        except Exception as exc:
            logger.debug("market_state_redis_persist_skipped", symbol=symbol, error=str(exc))

    def update_from_cycle(
        self,
        *,
        symbol: str,
        bar_index: int,
        regime: str,
        evidence: EvidenceBundle,
        forecast: Optional[MarketForecastBundle] = None,
        breakout_failed: bool = False,
    ) -> MarketStateTrajectory:
        traj = self.load(symbol)
        prev_trend = traj.last_evidence_summary.get("trend", 0.5)
        new_trend = evidence.get("trend", 0.5)
        traj.trend_strength_delta = new_trend - prev_trend
        prev_liq = traj.last_evidence_summary.get("liquidity", 0.5)
        traj.liquidity_drift = evidence.get("liquidity", 0.5) - prev_liq
        if breakout_failed:
            traj.failed_breakout_count += 1
        elif evidence.get("breakout", 0.5) >= 0.65:
            traj.failed_breakout_count = max(0, traj.failed_breakout_count - 1)
        traj.bar_index = int(bar_index)
        traj.regime_history.append(str(regime))
        traj.regime_history = traj.regime_history[-20:]
        traj.last_evidence_summary = dict(evidence.scores)
        if forecast is not None:
            traj.last_forecast = forecast.to_dict()
        self.persist(symbol, traj)
        return traj


market_state_engine = MarketStateEngine()
