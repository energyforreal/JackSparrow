"""
perpetual_data_fetcher.py
Fetches OHLCV, Funding Rate, Open Interest, and Mark Price from Delta Exchange India
with automatic pagination (handles the 2,000-candle-per-request limit).
Supported timeframes: 5m, 15m, 30m, 1h, 2h ONLY.
"""
import time
import requests
import pandas as pd
from typing import Optional
from pathlib import Path

BASE_URL = "https://api.india.delta.exchange/v2"
MAX_CANDLES_PER_REQUEST = 2000
REQUEST_DELAY_SECONDS = 0.25   # Respect rate limits

VALID_RESOLUTIONS = {"5m", "15m", "30m", "1h", "2h"}


def fetch_candles_paginated(
    symbol_query: str,
    resolution: str,
    start_ts: float,
    end_ts: float,
    verbose: bool = True,
    page_size: int = MAX_CANDLES_PER_REQUEST,
) -> list:
    assert resolution in VALID_RESOLUTIONS, (
        f"Invalid resolution '{resolution}'. "
        f"Allowed: {sorted(VALID_RESOLUTIONS)}"
    )

    all_candles = []
    current_start = start_ts
    batch_num = 0

    while current_start < end_ts:
        batch_num += 1
        params = {
            "symbol": symbol_query,
            "resolution": resolution,
            "start": int(current_start),
            "end": int(end_ts),
            "page_size": page_size,
        }
        try:
            resp = requests.get(
                f"{BASE_URL}/history/candles", params=params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [ERROR] {symbol_query} batch {batch_num}: {e}")
            break

        if not data.get("success") or not data.get("result"):
            break

        batch = data["result"]
        all_candles.extend(batch)

        if verbose:
            print(
                f"  [{symbol_query}] Batch {batch_num}: {len(batch)} candles "
                f"(total: {len(all_candles)})"
            )

        if len(batch) < page_size:
            break

        last_time = batch[-1]["time"]
        if last_time <= current_start:
            break
        current_start = last_time + 1

        time.sleep(REQUEST_DELAY_SECONDS)

    return all_candles


def fetch_candles_until_count(
    symbol_query: str,
    resolution: str,
    target_count: int,
    end_ts: Optional[float] = None,
    max_lookback_days: int = 730,
    verbose: bool = True,
) -> list:
    """Fetch at least `target_count` candles, going backward from end_ts."""
    assert resolution in VALID_RESOLUTIONS, (
        f"Invalid resolution '{resolution}'. "
        f"Allowed: {sorted(VALID_RESOLUTIONS)}"
    )
    assert target_count > 0, "target_count must be > 0"

    if end_ts is None:
        end_ts = time.time()

    period_seconds = {
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
    }[resolution]

    all_candles = []
    current_end = int(end_ts)
    lookback_limit_ts = int(current_end - max_lookback_days * 24 * 3600)

    loop = 0
    while len(all_candles) < target_count and current_end > lookback_limit_ts:
        loop += 1
        batch_start = max(0, current_end - MAX_CANDLES_PER_REQUEST * period_seconds)
        batch = fetch_candles_paginated(
            symbol_query,
            resolution,
            start_ts=batch_start,
            end_ts=current_end,
            verbose=verbose,
            page_size=MAX_CANDLES_PER_REQUEST,
        )

        if not batch:
            if verbose:
                print(f"  [WARN] No candles returned at loop {loop}. stopping")
            break

        # Prepend older candles, avoid duplicate times
        if all_candles and batch[-1]["time"] == all_candles[0]["time"]:
            batch = batch[:-1]
        all_candles = batch + all_candles

        if verbose:
            print(f"  [INFO] loop {loop}: collected {len(all_candles)} / {target_count} candles")

        first_ts = batch[0]["time"]
        if first_ts <= 0 or first_ts <= lookback_limit_ts:
            break

        current_end = first_ts - 1
        time.sleep(REQUEST_DELAY_SECONDS)

    # Trim to target_count latest candles
    if len(all_candles) > target_count:
        all_candles = all_candles[-target_count:]

    if verbose:
        print(f"  [RESULT] Total candles collected: {len(all_candles)}")

    return all_candles


def build_perpetual_feature_matrix(
    symbol: str = "BTCUSD",
    resolution: str = "1h",
    days_back: int = 90,
    end_ts: Optional[float] = None,
    save_path: Optional[Path] = None,
) -> pd.DataFrame:
    if end_ts is None:
        end_ts = time.time()
    start_ts = end_ts - (days_back * 24 * 3600)

    print(f"\n=== Building Perpetual Feature Matrix ===")
    print(f"Symbol: {symbol} | Resolution: {resolution} | Days: {days_back}")

    print("\n[1/4] Fetching OHLCV...")
    raw_ohlcv = fetch_candles_paginated(symbol, resolution, start_ts, end_ts)
    df_ohlcv = pd.DataFrame(raw_ohlcv)

    print("\n[2/4] Fetching Mark Price...")
    raw_mark = fetch_candles_paginated(f"MARK:{symbol}", resolution, start_ts, end_ts)
    df_mark = pd.DataFrame(raw_mark)[["time", "close"]].rename(columns={"close": "mark_price"})

    print("\n[3/4] Fetching Funding Rate...")
    raw_funding = fetch_candles_paginated(f"FUNDING:{symbol}", resolution, start_ts, end_ts)
    df_funding = pd.DataFrame(raw_funding)[["time", "close"]].rename(columns={"close": "funding_rate"})

    print("\n[4/4] Fetching Open Interest...")
    raw_oi = fetch_candles_paginated(f"OI:{symbol}", resolution, start_ts, end_ts)
    df_oi = pd.DataFrame(raw_oi)[["time", "close"]].rename(columns={"close": "open_interest"})

    df = df_ohlcv.merge(df_mark, on="time", how="left")
    df = df.merge(df_funding, on="time", how="left")
    df = df.merge(df_oi, on="time", how="left")

    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    df = df.drop(columns=["time"], errors="ignore")

    df[["funding_rate", "open_interest", "mark_price"]] = (
        df[["funding_rate", "open_interest", "mark_price"]].ffill()
    )

    print(f"\n✅ Feature matrix ready: {len(df)} rows × {len(df.columns)} columns")
    print(f"   Date range: {df.index[0]} → {df.index[-1]}")

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(save_path)
        print(f"   Saved to: {save_path}")

    return df


def get_live_orderbook_features(symbol: str = "BTCUSD") -> dict:
    try:
        resp = requests.get(f"{BASE_URL}/tickers/{symbol}", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("result", {}).get("quotes", {})
        bid_size = float(quotes.get("bid_size", 0))
        ask_size = float(quotes.get("ask_size", 0))
        total = bid_size + ask_size
        imbalance = (bid_size - ask_size) / total if total > 0 else 0.0
        return {
            "bid_size": bid_size,
            "ask_size": ask_size,
            "ob_imbalance": imbalance,
            "turnover_usd": float(data.get("result", {}).get("turnover_usd", 0)),
        }
    except Exception:
        return {"bid_size": 0, "ask_size": 0, "ob_imbalance": 0.0, "turnover_usd": 0}
