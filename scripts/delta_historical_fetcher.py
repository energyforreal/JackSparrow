"""Delta Exchange historical data batch fetcher

Creates a reusable `DeltaHistoricalDataFetcher` class to download OHLC candles
in 2000-candle batches with basic rate-limit handling, retries, and saving.

Usage example at bottom of file.

Dependencies: requests, pandas, pyarrow (optional for parquet)
pip install requests pandas pyarrow
"""
from __future__ import annotations

import time
import math
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path

import requests
import pandas as pd


class DeltaHistoricalDataFetcher:
    BASE_URLS = {
        "prod": "https://api.india.delta.exchange",
        "test": "https://cdn-ind.testnet.deltaex.org",
    }

    # Delta allows up to 2000 candles per request for /history/candles
    MAX_CANDLES_PER_REQUEST = 2000

    def __init__(self, env: str = "prod", user_agent: str = "delta-historical-fetcher/1.0"):
        self.base_url = self.BASE_URLS.get(env, env)
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": user_agent})

        # Simple rate-window accounting (10,000 units / 5 minutes; candle request costs 3 units)
        self.window_duration = 300.0
        self.max_units_per_window = 10000
        self.unit_cost_per_candle_request = 3
        self.units_used = 0
        self.window_start = time.time()

    def _ensure_rate_window(self):
        now = time.time()
        if now - self.window_start >= self.window_duration:
            self.units_used = 0
            self.window_start = now

    def _account_units(self, units: int):
        self._ensure_rate_window()
        if self.units_used + units > self.max_units_per_window:
            wait = self.window_duration - (time.time() - self.window_start) + 1
            if wait > 0:
                print(f"Rate window exceeded — sleeping {wait:.0f}s to reset quota")
                time.sleep(wait)
            self.units_used = 0
            self.window_start = time.time()
        self.units_used += units

    def _request_with_retry(self, path: str, params: Dict, retries: int = 3, backoff: float = 1.5) -> Dict:
        url = self.base_url.rstrip("/") + path
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=(5, 30))
                if resp.status_code == 429:
                    # If delta returns 429, try to respect retry-after header
                    ra = resp.headers.get("Retry-After")
                    wait = float(ra) if ra else 10.0
                    print(f"429 received. Waiting {wait}s before retrying...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    raise ValueError("Empty response JSON")
                return data
            except Exception as exc:
                if attempt == retries:
                    raise
                wait = backoff ** attempt
                print(f"Request failed (attempt {attempt}/{retries}): {exc} — retrying in {wait:.1f}s")
                time.sleep(wait)
        raise RuntimeError("unreachable")

    def fetch_historical_candles(
        self,
        symbol: str,
        resolution: str,
        start_ts: int,
        end_ts: int,
        data_type: str = "price",
    ) -> pd.DataFrame:
        """Fetch candles between start_ts and end_ts (unix seconds).

        Will split into <=2000-candle requests and concatenate results.
        """
        # path for candles
        path = "/v2/history/candles"

        # compute step size in seconds for resolution
        resolution_map = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
            "1d": 86400, "1w": 604800,
        }
        if resolution not in resolution_map:
            raise ValueError(f"Unsupported resolution: {resolution}")
        step = resolution_map[resolution]

        # compute total candles requested
        total_candles = max(0, (end_ts - start_ts) // step + 1)
        if total_candles == 0:
            return pd.DataFrame()

        n_chunks = math.ceil(total_candles / self.MAX_CANDLES_PER_REQUEST)
        frames = []

        for i in range(n_chunks):
            # newest-first approach: compute chunk end (exclusive)
            chunk_end = end_ts - i * self.MAX_CANDLES_PER_REQUEST * step
            chunk_start = max(start_ts, chunk_end - (self.MAX_CANDLES_PER_REQUEST - 1) * step)

            params = {
                "resolution": resolution,
                "symbol": symbol,
                "start": int(chunk_start),
                "end": int(chunk_end),
            }

            # account units and call
            self._account_units(self.unit_cost_per_candle_request)
            data = self._request_with_retry(path, params)

            # Delta's result may be inside 'result' key
            result = data.get("result") if isinstance(data, dict) else data
            if isinstance(result, dict):
                candles = result.get("candles", [])
            elif isinstance(result, list):
                candles = result
            else:
                candles = []

            if not candles:
                # nothing more to fetch
                break

            df = pd.DataFrame(candles)
            if "time" in df.columns:
                df = df.rename(columns={"time": "timestamp"})
            # ensure numeric
            for c in ["open", "high", "low", "close", "volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            frames.append(df)

            # small sleep to avoid tight loops
            time.sleep(0.12)

            # safety: stop if chunk_start==start_ts
            if chunk_start <= start_ts:
                break

        if not frames:
            return pd.DataFrame()

        # frames were fetched newest-first; concatenate and sort
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return out

    def fetch_range_by_dates(self, symbol: str, resolution: str, start_dt: str, end_dt: str) -> pd.DataFrame:
        """Convenience wrapper for ISO date strings (UTC assumed).

        start_dt, end_dt: e.g. '2024-01-01T00:00:00Z' or '2024-01-01'
        """
        def to_ts(s: str) -> int:
            dt = pd.to_datetime(s)
            if dt.tzinfo is None:
                dt = dt.tz_localize(timezone.utc)
            return int(dt.timestamp())

        start_ts = to_ts(start_dt)
        end_ts = to_ts(end_dt)
        return self.fetch_historical_candles(symbol, resolution, start_ts, end_ts)

    def save_to_csv(self, df: pd.DataFrame, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False)
        print(f"Saved CSV: {p}")

    def save_to_parquet(self, df: pd.DataFrame, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        print(f"Saved Parquet: {p}")


# -----------------------
# Example usage (run as script or import)
# -----------------------
if __name__ == "__main__":
    fetcher = DeltaHistoricalDataFetcher(env="prod")

    # Example: fetch one year of 1h candles (approx 8760 candles → ~5 requests)
    start = "2024-01-01"
    end = "2024-12-31"
    print(f"Fetching BTCUSD 1h from {start} to {end}...")
    df = fetcher.fetch_range_by_dates("BTCUSD", "1h", start, end)

    if not df.empty:
        out_dir = Path("data/backups/delta")
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "btcusd_1h_2024.csv"
        parquet_path = out_dir / "btcusd_1h_2024.parquet"
        fetcher.save_to_csv(df, str(csv_path))
        try:
            fetcher.save_to_parquet(df, str(parquet_path))
        except Exception:
            print("pyarrow not installed or parquet write failed; CSV saved")
    else:
        print("No data returned — check date range / symbol / API availability")
