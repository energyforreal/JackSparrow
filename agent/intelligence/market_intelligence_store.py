"""In-process and Redis persistence for MarketIntelligence snapshots."""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from agent.core.config import settings
from agent.core.redis_config import get_cache, set_cache
from agent.intelligence.market_intelligence import MarketIntelligence

logger = structlog.get_logger()

_STORE: Dict[str, MarketIntelligence] = {}
_VERSION: Dict[str, int] = {}


class MarketIntelligenceStore:
    """Latest MarketIntelligence per symbol with optional Redis mirror."""

    def __init__(self) -> None:
        self._local = _STORE
        self._versions = _VERSION

    def get(self, symbol: str) -> Optional[MarketIntelligence]:
        return self._local.get(str(symbol or "").strip().upper())

    async def put(self, intel: MarketIntelligence) -> MarketIntelligence:
        sym = str(intel.symbol or "").strip().upper()
        next_ver = self._versions.get(sym, 0) + 1
        intel.version = next_ver
        self._versions[sym] = next_ver
        self._local[sym] = intel

        if bool(getattr(settings, "market_intelligence_enabled", True)):
            ttl = int(getattr(settings, "market_intel_redis_ttl_seconds", 300) or 300)
            try:
                await set_cache(f"market_intel:{sym}", intel.to_dict(), ttl=ttl)
            except Exception as e:
                logger.debug(
                    "market_intelligence_redis_put_failed",
                    symbol=sym,
                    error=str(e),
                )
        return intel

    async def load_from_redis(self, symbol: str) -> Optional[Dict[str, Any]]:
        sym = str(symbol or "").strip().upper()
        try:
            cached = await get_cache(f"market_intel:{sym}")
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass
        return None

    def clear(self, symbol: Optional[str] = None) -> None:
        if symbol:
            sym = str(symbol).strip().upper()
            self._local.pop(sym, None)
            self._versions.pop(sym, None)
        else:
            self._local.clear()
            self._versions.clear()

    def get_health_summary(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Health payload for orchestrator / API dashboards."""
        if symbol:
            sym = str(symbol or "").strip().upper()
            intel = self.get(sym)
            if intel is None:
                return {"status": "empty", "symbol": sym}
            return {
                "status": "up",
                "symbol": sym,
                "version": intel.version,
                "regime": intel.regime,
                "bar_index": intel.bar_index,
                "snapshot": intel.to_dict(),
            }
        symbols = sorted(self._local.keys())
        return {
            "status": "up" if symbols else "empty",
            "symbol_count": len(symbols),
            "symbols": symbols,
            "versions": {k: self._versions.get(k, 0) for k in symbols},
        }


market_intelligence_store = MarketIntelligenceStore()
