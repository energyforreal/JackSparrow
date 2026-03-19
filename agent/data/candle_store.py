"""
Historical candle persistence: Parquet-based storage for raw OHLCV candles.

Enables reproducible training, backtesting on exact data, and incremental training.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

logger = structlog.get_logger()

# Default storage root (relative to project root)
DEFAULT_STORAGE_ROOT = Path("data/candles")


class CandleStore:
    """Persists raw OHLCV candles to Parquet with deduplication by timestamp."""

    def __init__(self, storage_root: Optional[Path] = None):
        """
        Initialize candle store.

        Args:
            storage_root: Root directory for Parquet files. Default: data/candles
        """
        self._root = Path(storage_root) if storage_root else DEFAULT_STORAGE_ROOT

    def _parquet_path(self, symbol: str, interval: str) -> Path:
        """Path to Parquet file for symbol/interval."""
        return self._root / symbol / f"{interval}.parquet"

    def append(
        self,
        symbol: str,
        interval: str,
        candles: List[Dict[str, Any]],
    ) -> None:
        """
        Append candles to storage. Deduplicates by timestamp.

        Args:
            symbol: Trading symbol (e.g., BTCUSD)
            interval: Candle interval (e.g., 15m, 1h)
            candles: List of candle dicts with open, high, low, close, volume, timestamp
        """
        if not candles:
            return

        df = pd.DataFrame(candles)
        required = ["open", "high", "low", "close", "volume", "timestamp"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning(
                "candle_store_skip_append_missing_columns",
                symbol=symbol,
                interval=interval,
                missing=missing,
            )
            return

        # Normalize timestamp to int (Unix seconds)
        ts = df["timestamp"]
        if pd.api.types.is_datetime64_any_dtype(ts):
            df["timestamp"] = ts.astype("int64") // 10**9
        elif ts.dtype == object or ts.dtype == float:
            df["timestamp"] = pd.to_numeric(ts, errors="coerce").fillna(0).astype(int)

        path = self._parquet_path(symbol, interval)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if path.exists():
                existing = pd.read_parquet(path)
                df = pd.concat([existing, df], ignore_index=True)
                df = df.drop_duplicates(subset=["timestamp"], keep="last")
                df = df.sort_values("timestamp").reset_index(drop=True)
            df.to_parquet(path, index=False)
            logger.debug(
                "candle_store_appended",
                symbol=symbol,
                interval=interval,
                rows=len(df),
            )
        except Exception as e:
            logger.error(
                "candle_store_append_failed",
                symbol=symbol,
                interval=interval,
                error=str(e),
                exc_info=True,
            )

    def query(
        self,
        symbol: str,
        interval: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Query candles by time range.

        Args:
            symbol: Trading symbol
            interval: Candle interval
            start: Start timestamp (Unix seconds, inclusive)
            end: End timestamp (Unix seconds, inclusive)

        Returns:
            DataFrame with columns open, high, low, close, volume, timestamp
        """
        path = self._parquet_path(symbol, interval)
        if not path.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "timestamp"])

        try:
            df = pd.read_parquet(path)
            if start is not None:
                df = df[df["timestamp"] >= start]
            if end is not None:
                df = df[df["timestamp"] <= end]
            return df.sort_values("timestamp").reset_index(drop=True)
        except Exception as e:
            logger.error(
                "candle_store_query_failed",
                symbol=symbol,
                interval=interval,
                error=str(e),
                exc_info=True,
            )
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "timestamp"])
