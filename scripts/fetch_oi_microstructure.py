#!/usr/bin/env python3
"""Fetch Delta OI + microstructure history into v43 ticker CSV schema.

Outputs CSV columns matching ``agent.core.v43_oi_frames.TICKER_RING_COLUMNS`` so
the file can be used directly as ``V43_OI_HISTORY_CSV`` in the Colab notebook.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import requests

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent.core.v43_oi_frames import TICKER_RING_COLUMNS  # noqa: E402
from agent.data.historical_data_loader import fetch_historical_candles  # noqa: E402
from feature_store.jacksparrow_v43_oi_history import oi_candles_to_ticker_frame  # noqa: E402

BASE_URL = "https://api.india.delta.exchange"


def _safe_float(val: Any, fallback: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return fallback


def _fetch_live_ticker_snapshot(symbol: str) -> Dict[str, float]:
    url = f"{BASE_URL}/v2/tickers/{symbol}"
    resp = requests.get(url, timeout=20, headers={"Accept": "application/json"})
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"Delta ticker API failure: {payload}")
    result = payload.get("result") or {}
    quotes = result.get("quotes") or {}
    price_band = result.get("price_band") or {}
    return {
        "oi_contracts": _safe_float(result.get("oi") or result.get("oi_contracts"), 0.0),
        "oi_value_usd": _safe_float(
            result.get("oi_value_usd") or result.get("oi_value"), 0.0
        ),
        "mark_price": _safe_float(result.get("mark_price"), 0.0),
        "spot_price": _safe_float(result.get("spot_price"), 0.0),
        "best_bid": _safe_float(quotes.get("best_bid"), 0.0),
        "best_ask": _safe_float(quotes.get("best_ask"), 0.0),
        "bid_size": _safe_float(quotes.get("bid_size"), 0.0),
        "ask_size": _safe_float(quotes.get("ask_size"), 0.0),
        "price_band_upper": _safe_float(price_band.get("upper_limit"), 0.0),
        "price_band_lower": _safe_float(price_band.get("lower_limit"), 0.0),
        "predicted_funding_rate": _safe_float(
            result.get("predicted_funding_rate") or result.get("funding_rate"),
            0.0,
        ),
        "taker_buy_ratio": 0.5,
    }


def _prep_history_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "timestamp" not in out.columns and "time" in out.columns:
        out["timestamp"] = pd.to_datetime(out["time"], unit="s", utc=True)
    elif "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Delta OI + microstructure CSV")
    parser.add_argument("--symbol", default="BTCUSD", help="Delta contract symbol")
    parser.add_argument(
        "--candles",
        type=int,
        default=200000,
        help="Target number of bars per history pull",
    )
    parser.add_argument(
        "--resolution",
        default="5m",
        choices=["5m", "15m", "30m", "1h", "2h"],
        help="Candle resolution",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO / "data" / "oi_microstructure_BTCUSD.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    symbol = str(args.symbol).strip().upper()
    print(f"[1/4] Fetching OI:{symbol} {args.resolution} candles...")
    df_oi_raw = fetch_historical_candles(
        symbol=f"OI:{symbol}",
        resolution=args.resolution,
        target_count=int(args.candles),
        aggressive=False,
    )
    if df_oi_raw.empty:
        print("No OI candles returned.", file=sys.stderr)
        return 1

    print(f"[2/4] Fetching MARK:{symbol} {args.resolution} candles...")
    df_mark_raw = fetch_historical_candles(
        symbol=f"MARK:{symbol}",
        resolution=args.resolution,
        target_count=int(args.candles),
        aggressive=False,
    )

    print(f"[3/4] Fetching live ticker snapshot {symbol}...")
    ticker = _fetch_live_ticker_snapshot(symbol)

    print("[4/4] Building aligned ticker frame...")
    df_oi = _prep_history_df(df_oi_raw)
    df_mark = _prep_history_df(df_mark_raw) if not df_mark_raw.empty else df_mark_raw
    df_ticker = oi_candles_to_ticker_frame(df_oi, df_mark=df_mark, align_to=df_oi)

    # Use most recent public ticker snapshot as a microstructure proxy if these columns
    # are absent/empty in historical OI candles.
    for col in (
        "best_bid",
        "best_ask",
        "bid_size",
        "ask_size",
        "price_band_upper",
        "price_band_lower",
        "predicted_funding_rate",
    ):
        if col not in df_ticker.columns or float(pd.to_numeric(df_ticker[col], errors="coerce").abs().max()) < 1e-12:
            df_ticker[col] = ticker[col]
    if "oi_value_usd" in df_ticker.columns and float(
        pd.to_numeric(df_ticker["oi_value_usd"], errors="coerce").abs().max()
    ) < 1e-12:
        mark = pd.to_numeric(df_ticker.get("mark_price", 0.0), errors="coerce").fillna(0.0)
        oi = pd.to_numeric(df_ticker.get("oi_contracts", 0.0), errors="coerce").fillna(0.0)
        df_ticker["oi_value_usd"] = oi * mark
    df_ticker["spot_price"] = pd.to_numeric(df_ticker.get("spot_price", 0.0), errors="coerce").fillna(0.0)
    if float(df_ticker["spot_price"].abs().max()) < 1e-12 and float(
        pd.to_numeric(df_ticker.get("mark_price", 0.0), errors="coerce").abs().max()
    ) > 0:
        df_ticker["spot_price"] = pd.to_numeric(df_ticker["mark_price"], errors="coerce").fillna(0.0)

    for col in TICKER_RING_COLUMNS:
        if col not in df_ticker.columns:
            df_ticker[col] = 0.5 if col == "taker_buy_ratio" else 0.0
    df_ticker = df_ticker[list(TICKER_RING_COLUMNS)]
    df_ticker["timestamp"] = pd.to_datetime(df_ticker["timestamp"], utc=True)
    df_ticker = df_ticker.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df_ticker.to_csv(args.out, index=False)
    print(f"Wrote {len(df_ticker)} rows -> {args.out}")
    print("Use in Colab:")
    print(f'  os.environ["V43_OI_HISTORY_CSV"] = "{args.out}"')
    print('  os.environ["V43_ALLOW_EMPTY_OI_FOR_TRAINING"] = "false"')
    print(f"Done @ {int(time.time())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

