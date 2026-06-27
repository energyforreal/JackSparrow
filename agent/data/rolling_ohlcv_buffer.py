"""In-process rolling OHLCV buffers with incremental tail fetch."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from agent.data.candle_validation import dataframe_from_delta_candles

INCREMENTAL_TAIL_BARS = 3

_RESOLUTION_SECONDS: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
}


def resolution_seconds(resolution: str) -> int:
    return _RESOLUTION_SECONDS.get(str(resolution or "").lower(), 3600)


def normalize_delta_candles(raw: List[dict[str, Any]]) -> List[dict[str, Any]]:
    """Normalize Delta history/candles rows to candle_validation format."""
    out: List[dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        ts = c.get("time")
        if ts is None:
            continue
        out.append(
            {
                "timestamp": ts,
                "open": float(c.get("open", 0) or 0),
                "high": float(c.get("high", 0) or 0),
                "low": float(c.get("low", 0) or 0),
                "close": float(c.get("close", 0) or 0),
                "volume": float(c.get("volume", 0) or 0),
            }
        )
    return out


def parse_candles_response(resp: Any) -> List[dict[str, Any]]:
    candles: List[dict[str, Any]] = []
    if isinstance(resp, dict):
        result = resp.get("result")
        if isinstance(result, dict):
            candles = result.get("candles", []) or []
        elif isinstance(result, list):
            candles = result
    elif isinstance(resp, list):
        candles = resp
    return normalize_delta_candles([c for c in candles if isinstance(c, dict)])


class RollingOhlcvBufferRegistry:
    """symbol -> resolution -> OHLCV DataFrame with incremental merge."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, pd.DataFrame]] = {}

    def get(self, symbol: str, resolution: str) -> Optional[pd.DataFrame]:
        sym = self._store.get(symbol, {})
        df = sym.get(resolution)
        if df is None or df.empty:
            return None
        return df.copy()

    def put(self, symbol: str, resolution: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        self._store.setdefault(symbol, {})[resolution] = df.reset_index(drop=True)

    def hydrate_from_store(
        self,
        candle_store: Any,
        symbol: str,
        resolution: str,
        n_bars: int,
    ) -> bool:
        """Seed buffer from CandleStore tail when empty (restart gap-fetch)."""
        cached = self.get(symbol, resolution)
        if cached is not None and not cached.empty and len(cached) >= n_bars:
            return True
        if not hasattr(candle_store, "load_tail"):
            return False
        df = candle_store.load_tail(symbol, resolution, n_bars)
        if df is None or df.empty:
            return False
        if "timestamp" in df.columns:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        self.put(symbol, resolution, df)
        return True

    def clear(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self._store.pop(symbol, None)
        else:
            self._store.clear()

    async def fetch_incremental(
        self,
        delta_client: Any,
        symbol: str,
        resolution: str,
        n_candles: int,
        *,
        use_incremental_cache: bool = True,
    ) -> pd.DataFrame:
        """Fetch last n_candles bars ending now (incremental append when cached)."""
        bar_seconds = resolution_seconds(resolution)
        end_ts = int(datetime.now(timezone.utc).timestamp())
        cached = self.get(symbol, resolution) if use_incremental_cache else None

        cache_ready = (
            use_incremental_cache
            and cached is not None
            and not cached.empty
            and "timestamp" in cached.columns
            and len(cached) >= n_candles
        )
        if cache_ready:
            start_ts = end_ts - int(INCREMENTAL_TAIL_BARS * bar_seconds * 2)
        else:
            start_ts = end_ts - int(n_candles * bar_seconds * 1.05)

        resp = await delta_client.get_candles(
            symbol=symbol,
            resolution=resolution,
            start=start_ts,
            end=end_ts,
        )
        formatted = parse_candles_response(resp)
        fresh = dataframe_from_delta_candles(formatted)
        if fresh.empty:
            return cached.copy() if cached is not None and not cached.empty else fresh

        if cached is not None and not cached.empty and use_incremental_cache:
            combined = (
                pd.concat([cached, fresh], ignore_index=True)
                .drop_duplicates(subset=["timestamp"], keep="last")
                .sort_values("timestamp")
            )
            # Never shrink below existing cache (e.g. candle poll with limit=10).
            keep_rows = max(n_candles, len(cached))
            out = combined.tail(keep_rows).reset_index(drop=True)
        else:
            out = fresh.tail(n_candles).reset_index(drop=True)

        self.put(symbol, resolution, out)
        return out

    def to_formatted_candles(self, symbol: str, resolution: str, limit: int) -> List[Dict[str, Any]]:
        """Convert buffered frame to MarketDataService candle dict format."""
        df = self.get(symbol, resolution)
        if df is None or df.empty:
            return []
        tail = df.tail(limit)
        out: List[Dict[str, Any]] = []
        for _, row in tail.iterrows():
            ts = row.get("timestamp")
            if hasattr(ts, "timestamp"):
                ts_val = int(ts.timestamp())
            else:
                try:
                    ts_val = int(pd.Timestamp(ts).timestamp())
                except (TypeError, ValueError):
                    continue
            out.append(
                {
                    "timestamp": ts_val,
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)),
                }
            )
        return out
