"""Public Delta India history fetch for Colab transformer training."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pandas as pd
import requests

_RESOLUTION_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
}


def fetch_candles(
    symbol: str,
    resolution: str,
    start_ts: int,
    end_ts: int,
    base_url: str,
) -> pd.DataFrame:
    """Paginated pull of OHLC-style candles from Delta India public history API."""
    url = f"{base_url}/v2/history/candles"
    all_rows = []
    resolution_minutes = _RESOLUTION_MINUTES[resolution]
    chunk_seconds = resolution_minutes * 60 * 2000

    cur_start = start_ts
    while cur_start < end_ts:
        cur_end = min(cur_start + chunk_seconds, end_ts)
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": cur_start,
            "end": cur_end,
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("result", [])
        if rows:
            all_rows.extend(rows)
        cur_start = cur_end
        time.sleep(0.2)

    if not all_rows:
        raise RuntimeError(
            f"No candle data returned for symbol={symbol}; check symbol/resolution/date range."
        )

    df = pd.DataFrame(all_rows)
    expected_cols = ["time", "open", "high", "low", "close", "volume"]
    df = df[[c for c in expected_cols if c in df.columns]]
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def validate_derivatives_coverage(
    df: pd.DataFrame,
    *,
    min_coverage: float = 0.5,
    warn_coverage: float = 0.9,
) -> Dict[str, Any]:
    """Check funding/OI non-null coverage over the OHLCV timeline."""
    n = len(df)
    if n == 0:
        raise ValueError("Cannot validate derivatives coverage on empty frame")

    report: Dict[str, Any] = {"rows": n, "columns": {}}
    for col in ("funding_rate", "open_interest"):
        if col not in df.columns:
            report["columns"][col] = {"coverage": 0.0, "status": "missing"}
            continue
        coverage = float(df[col].notna().mean())
        status = "ok"
        if coverage < min_coverage:
            status = "error"
        elif coverage < warn_coverage:
            status = "warn"
        report["columns"][col] = {
            "coverage": round(coverage, 4),
            "status": status,
        }

    worst = min(v["coverage"] for v in report["columns"].values())
    report["worst_coverage"] = worst
    if worst < min_coverage:
        raise ValueError(
            "Derivatives coverage below minimum "
            f"({worst:.1%} < {min_coverage:.0%}): {report['columns']}"
        )
    return report


def fetch_history_bundle(
    *,
    symbol: str,
    resolution: str,
    history_days: int,
    base_url: str,
    min_derivatives_coverage: float = 0.5,
    derivatives_coverage_warn: float = 0.9,
) -> pd.DataFrame:
    """Fetch OHLCV + funding + OI merged frame (notebook-compatible)."""
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=history_days)
    start_ts, end_ts = int(start_dt.timestamp()), int(end_dt.timestamp())

    raw_df = fetch_candles(symbol, resolution, start_ts, end_ts, base_url)

    try:
        funding_df = fetch_candles(
            f"FUNDING:{symbol}", resolution, start_ts, end_ts, base_url
        )
        funding_df = funding_df[["time", "close"]].rename(columns={"close": "funding_rate"})
    except Exception:
        funding_df = pd.DataFrame({"time": [], "funding_rate": []})

    try:
        oi_df = fetch_candles(f"OI:{symbol}", resolution, start_ts, end_ts, base_url)
        oi_df = oi_df[["time", "close"]].rename(columns={"close": "open_interest"})
    except Exception:
        oi_df = pd.DataFrame({"time": [], "open_interest": []})

    raw_df = raw_df.merge(funding_df, on="time", how="left")
    raw_df = raw_df.merge(oi_df, on="time", how="left")
    raw_df["funding_rate"] = raw_df["funding_rate"].ffill()
    raw_df["open_interest"] = raw_df["open_interest"].ffill()

    report = validate_derivatives_coverage(
        raw_df,
        min_coverage=min_derivatives_coverage,
        warn_coverage=derivatives_coverage_warn,
    )
    for col, info in report["columns"].items():
        if info["status"] == "warn":
            print(
                f"WARNING: {col} coverage {info['coverage']:.1%} "
                f"below recommended {derivatives_coverage_warn:.0%}"
            )
        elif info["status"] == "ok":
            print(f"{col} coverage: {info['coverage']:.1%}")

    return raw_df
