#!/usr/bin/env python3
"""Runtime bug probe for Delta testnet integration (debug session 38bab1)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG_PATH = ROOT / "debug-38bab1.log"
SESSION = "38bab1"


def _log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    entry = {
        "sessionId": SESSION,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "runId": "bug-probe-1",
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


async def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    from agent.data.delta_client import DeltaExchangeClient, DeltaExchangeError

    client = DeltaExchangeClient()
    symbol = "BTCUSD"

    # H-A: product_id resolution vs env
    pid = await client.resolve_product_id(symbol)
    env_pid = int(getattr(__import__("agent.core.config", fromlist=["settings"]).settings, "product_id", 0) or 0)
    _log("A", "bug_probe:resolve", "product_id_resolved", {"resolved": pid, "env_product_id": env_pid})

    # H-B: place_order payload keys (no dual product_id+symbol)
    place = await client.place_order(symbol, "buy", 1, "MARKET")
    result = place.get("result") or {}
    order = result.get("order") if isinstance(result.get("order"), dict) else result
    _log(
        "B",
        "bug_probe:place",
        "place_order_response",
        {
            "success": place.get("success"),
            "order_keys": sorted(order.keys()) if isinstance(order, dict) else str(type(order)),
            "id": order.get("id") if isinstance(order, dict) else None,
            "state": order.get("state") if isinstance(order, dict) else None,
            "average_fill_price": order.get("average_fill_price") if isinstance(order, dict) else None,
            "price": order.get("price") if isinstance(order, dict) else None,
        },
    )

    # H-C: fill price derivable for execution engine
    fill_keys = {k: order.get(k) for k in ("average_fill_price", "avg_fill_price", "limit_price", "price", "state")}
    _log("C", "bug_probe:fill", "fill_price_fields", fill_keys)

    # H-D: get_positions product_id path
    pos = await client.get_positions(product_id=pid)
    _log("D", "bug_probe:positions", "get_positions", {"result": pos.get("result")})

    # H-E: fractional size rejected
    frac_err = None
    try:
        await client.place_order(symbol, "sell", 1.5, "MARKET", reduce_only=True)
    except DeltaExchangeError as e:
        frac_err = str(e)
    _log("E", "bug_probe:fractional", "fractional_rejected", {"error": frac_err})

    # H-F: close reduce_only
    size = 0
    if isinstance(pos.get("result"), dict):
        try:
            size = int(float(pos["result"].get("size") or 0))
        except (TypeError, ValueError):
            size = 0
    if size != 0:
        close_side = "sell" if size > 0 else "buy"
        close = await client.place_order(
            symbol, close_side, abs(size), "MARKET", reduce_only=True
        )
        cres = close.get("result") or {}
        corder = cres.get("order") if isinstance(cres.get("order"), dict) else cres
        _log(
            "F",
            "bug_probe:close",
            "reduce_only_close",
            {
                "success": close.get("success"),
                "state": corder.get("state") if isinstance(corder, dict) else None,
                "average_fill_price": corder.get("average_fill_price") if isinstance(corder, dict) else None,
            },
        )

    _log("OK", "bug_probe:done", "probe_complete", {})
    return 0


if __name__ == "__main__":
    asyncio.run(main())
