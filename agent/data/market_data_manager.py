"""Unified market data authority: streaming, OHLCV buffers, and v43 frames."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import structlog

from agent.core.config import settings
from agent.core.v43_contract_state import ContractStateSnapshot, get_contract_state
from agent.core.v43_market_frames import closed_5m_bar_index, fetch_v43_market_frames
from agent.core.v43_oi_frames import push_oi_from_ws_ticker
from agent.data.market_data_service import MarketDataService
from agent.data.rolling_ohlcv_buffer import RollingOhlcvBufferRegistry
from agent.data.symbols import normalize_symbol_for_delta_api

logger = structlog.get_logger()

_V43_WARM_LIMITS: Dict[str, int] = {
    "1m": 100,
    "5m": 100,
    "15m": 100,
    "30m": 100,
    "1h": 100,
    "2h": 100,
}


@dataclass
class V43FramesBundle:
    """Multi-timeframe frames for v43 / IC inference."""

    df5m: pd.DataFrame
    df15m: pd.DataFrame
    df1h: pd.DataFrame
    df_funding: pd.DataFrame
    df_oi: pd.DataFrame
    df_mark: pd.DataFrame

    @property
    def closed_bar_index(self) -> int:
        return closed_5m_bar_index(self.df5m)


class MarketDataManager(MarketDataService):
    """Single owner for live OHLCV buffers, streaming, and v43 frame access."""

    def __init__(self, delta_client: Optional[Any] = None) -> None:
        super().__init__()
        if delta_client is not None:
            self.delta_client = delta_client
        self._ohlcv_buffers = RollingOhlcvBufferRegistry()

    @property
    def ohlcv_buffers(self) -> RollingOhlcvBufferRegistry:
        return self._ohlcv_buffers

    async def get_ohlcv_df(
        self,
        symbol: str,
        interval: str,
        limit: int,
        *,
        use_incremental_cache: bool = True,
    ) -> pd.DataFrame:
        """Fetch or return buffered OHLCV as DataFrame."""
        sym = normalize_symbol_for_delta_api(symbol)
        iv = str(interval or "1h").strip().lower()
        n = max(2, int(limit))
        return await self._ohlcv_buffers.fetch_incremental(
            self.delta_client,
            sym,
            iv,
            n,
            use_incremental_cache=use_incremental_cache,
        )

    async def warm_timeframes(
        self,
        symbol: str,
        intervals: List[str],
        *,
        limit: int = 100,
    ) -> None:
        """Prefetch OHLCV for configured timeframes into shared buffers."""
        seen: set[str] = set()
        sym = normalize_symbol_for_delta_api(symbol)
        for raw_iv in intervals or []:
            iv = str(raw_iv or "").strip().lower()
            if not iv or iv in seen:
                continue
            seen.add(iv)
            want = max(limit, _V43_WARM_LIMITS.get(iv, limit))
            try:
                await self.get_ohlcv_df(sym, iv, want)
            except Exception as e:
                logger.debug(
                    "market_data_manager_warm_failed",
                    symbol=sym,
                    interval=iv,
                    error=str(e),
                )

    async def get_v43_frames(self, symbol: str) -> V43FramesBundle:
        """Load v43 frames using shared OHLCV buffers; warm active timeframes once."""
        sym = normalize_symbol_for_delta_api(symbol)
        mtf = settings.resolved_agent_timeframes()
        if mtf:
            await self.warm_timeframes(sym, mtf)

        df5, df15, df1h, df_fund, df_oi, df_mark = await fetch_v43_market_frames(
            self.delta_client,
            sym,
            buffer_registry=self._ohlcv_buffers,
        )
        return V43FramesBundle(
            df5m=df5,
            df15m=df15,
            df1h=df1h,
            df_funding=df_fund,
            df_oi=df_oi,
            df_mark=df_mark,
        )

    async def get_contract_state_for_symbol(
        self,
        symbol: str,
        ticker_row: Optional[Dict[str, Any]] = None,
    ) -> ContractStateSnapshot:
        return await get_contract_state(symbol, ticker_row=ticker_row)

    def headline_price(self, symbol: str) -> Optional[float]:
        return self.get_cached_headline_price(symbol)

    async def get_market_data(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """Get market data; prefer in-process OHLCV buffers when manager is enabled."""
        if not bool(getattr(settings, "market_data_manager_enabled", True)):
            return await super().get_market_data(symbol, interval, limit)

        sym = normalize_symbol_for_delta_api(symbol)
        iv = str(interval or "1h").strip().lower()
        want = max(1, int(limit))

        cached_df = self._ohlcv_buffers.get(sym, iv)
        if cached_df is not None and len(cached_df) >= want:
            formatted = self._ohlcv_buffers.to_formatted_candles(sym, iv, want)
            ticker = await self.get_ticker(sym)
            current_price = ticker.get("close") if ticker else None
            return {
                "symbol": sym,
                "interval": iv,
                "candles": formatted,
                "current_price": current_price,
                "data_age_seconds": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        df = await self.get_ohlcv_df(sym, iv, want)
        if df.empty:
            return await super().get_market_data(symbol, interval, limit)

        formatted = self._ohlcv_buffers.to_formatted_candles(sym, iv, want)
        ticker = await self.get_ticker(sym)
        current_price = ticker.get("close") if ticker else None
        return {
            "symbol": sym,
            "interval": iv,
            "candles": formatted,
            "current_price": current_price,
            "data_age_seconds": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def warm_multi_timeframe_caches(
        self,
        symbol: str,
        intervals: List[str],
        *,
        limit: int = 100,
    ) -> None:
        """Backward-compatible alias for warm_timeframes."""
        await self.warm_timeframes(symbol, intervals, limit=limit)

    async def _on_tick(self, symbol: str, ticker_data: Dict[str, Any]) -> None:
        """Push WS ticker microstructure into OI ring before emitting tick."""
        try:
            push_oi_from_ws_ticker(symbol, ticker_data)
        except Exception as e:
            logger.debug(
                "market_data_manager_oi_ring_push_failed",
                symbol=symbol,
                error=str(e),
            )
        await super()._on_tick(symbol, ticker_data)


def create_market_data_layer(delta_client: Optional[Any] = None) -> MarketDataService:
    """Factory: return MarketDataManager when enabled, else legacy MarketDataService."""
    if bool(getattr(settings, "market_data_manager_enabled", True)):
        return MarketDataManager(delta_client=delta_client)
    svc = MarketDataService()
    if delta_client is not None:
        svc.delta_client = delta_client
    return svc
