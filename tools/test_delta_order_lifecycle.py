#!/usr/bin/env python3
"""
Delta testnet order lifecycle smoke test.

Exercises: resolve product_id, GET/POST order leverage, place market order,
list active orders, read position, close via reduce_only market order.

Usage:
  python tools/test_delta_order_lifecycle.py --allow-live
  python tools/test_delta_order_lifecycle.py --allow-live --symbol BTCUSD --skip-place
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from agent.data.delta_client import DeltaExchangeClient, DeltaExchangeError


def _is_testnet_url(url: str) -> bool:
    return "testnet" in (url or "").lower()


async def run_smoke(symbol: str, skip_place: bool) -> int:
    base = (
        os.getenv("DELTA_EXCHANGE_BASE_URL")
        or os.getenv("DELTA_API_URL")
        or "https://cdn-ind.testnet.deltaex.org"
    )
    client = DeltaExchangeClient()
    print(f"Base URL: {client.base_url}")
    print(f"Symbol: {symbol}")

    product_id = await client.resolve_product_id(symbol)
    print(f"Resolved product_id: {product_id}")

    print("Order leverage (GET)...")
    try:
        lev_get = await client.get_order_leverage(product_id=product_id)
        current = client._parse_order_leverage_value(lev_get)
        print(f"  current leverage={current}")
    except DeltaExchangeError as exc:
        print(f"  GET leverage failed (may be unset): {exc}")
        current = None

    target_leverage = 10
    print(f"Order leverage sync (ensure {target_leverage})...")
    lev_set = await client.ensure_order_leverage(symbol, target_leverage)
    synced = client._parse_order_leverage_value(lev_set)
    print(f"  synced leverage={synced}")

    lev_verify = await client.get_order_leverage(product_id=product_id)
    verified = client._parse_order_leverage_value(lev_verify)
    print(f"  verified leverage={verified}")

    if not skip_place:
        print("Placing 1-lot market buy (testnet)...")
        place = await client.place_order(symbol, "buy", 1, "MARKET")
        order = place.get("result") or {}
        if isinstance(order.get("order"), dict):
            order = order["order"]
        print(f"  place success={place.get('success')} id={order.get('id')} state={order.get('state')}")

    print("Active orders...")
    active = await client.get_orders(
        product_ids=str(product_id), states="open,pending", page_size=5
    )
    rows = active.get("result") or []
    print(f"  active count={len(rows) if isinstance(rows, list) else 'n/a'}")

    print("Real-time position...")
    pos = await client.get_positions(product_id=product_id)
    print(f"  position result keys={list((pos.get('result') or {}).keys()) if isinstance(pos.get('result'), dict) else type(pos.get('result'))}")

    print("Margined positions...")
    margined = await client.get_margined_positions(contract_types="perpetual_futures")
    mres = margined.get("result") or []
    print(f"  margined count={len(mres) if isinstance(mres, list) else 'n/a'}")

    size = 0
    if isinstance(pos.get("result"), dict):
        try:
            size = int(float(pos["result"].get("size") or 0))
        except (TypeError, ValueError):
            size = 0

    if size != 0:
        close_side = "sell" if size > 0 else "buy"
        lots = abs(size)
        print(f"Closing position reduce_only {close_side} {lots} lot(s)...")
        close = await client.place_order(
            symbol,
            close_side,
            lots,
            "MARKET",
            reduce_only=True,
        )
        corder = close.get("result") or {}
        if isinstance(corder.get("order"), dict):
            corder = corder["order"]
        print(f"  close success={close.get('success')} id={corder.get('id')} state={corder.get('state')}")
    else:
        print("No open position to close.")

    print("Order history (last 5)...")
    hist = await client.get_orders_history(product_ids=str(product_id), page_size=5)
    hres = hist.get("result") or []
    print(f"  history count={len(hres) if isinstance(hres, list) else 'n/a'}")

    print("Smoke completed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Delta testnet order lifecycle smoke test")
    parser.add_argument("--symbol", default="BTCUSD")
    parser.add_argument("--skip-place", action="store_true", help="Skip opening leg; only read/close")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Required when base URL is production (not testnet)",
    )
    args = parser.parse_args()

    base = os.getenv("DELTA_EXCHANGE_BASE_URL") or os.getenv("DELTA_API_URL") or ""
    if base and not _is_testnet_url(base) and not args.allow_live:
        print(
            "Refusing production URL without --allow-live. "
            "Use testnet DELTA_EXCHANGE_BASE_URL or pass --allow-live."
        )
        sys.exit(2)

    try:
        code = asyncio.run(run_smoke(args.symbol.upper(), args.skip_place))
    except DeltaExchangeError as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(130)
    sys.exit(code)


if __name__ == "__main__":
    main()
