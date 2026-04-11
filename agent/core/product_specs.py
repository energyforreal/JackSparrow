"""
Resolve Delta Exchange India perpetual contract specs (contract value, tick size).

Uses public GET /v2/products/{symbol} with Redis cache; no API key required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import structlog

from agent.core.config import settings
from agent.core.redis_config import get_cache, set_cache

logger = structlog.get_logger()

CACHE_KEY_PREFIX = "delta:product_specs:"


@dataclass(frozen=True)
class ContractSpecs:
    """Paper model inputs aligned with Delta product metadata."""

    symbol: str
    contract_value_btc: float
    tick_size: float
    product_id: int
    taker_commission_rate: Optional[float] = None


def _parse_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _product_result_to_specs(symbol: str, result: Dict[str, Any]) -> ContractSpecs:
    cv = _parse_float(result.get("contract_value"), float(getattr(settings, "contract_value_btc", 0.001)))
    tick = _parse_float(result.get("tick_size"), float(getattr(settings, "tick_size", 0.5)))
    pid = int(result.get("id") or getattr(settings, "product_id", 27))
    taker = result.get("taker_commission_rate")
    taker_f = _parse_float(taker, float(getattr(settings, "taker_fee_rate", 0.0005))) if taker is not None else None
    return ContractSpecs(
        symbol=str(result.get("symbol") or symbol).upper(),
        contract_value_btc=cv,
        tick_size=tick,
        product_id=pid,
        taker_commission_rate=taker_f,
    )


async def _fetch_product_public(symbol: str) -> Dict[str, Any]:
    base = (getattr(settings, "delta_exchange_base_url", None) or "").rstrip("/")
    if not base:
        base = "https://api.india.delta.exchange"
    url = f"{base}/v2/products/{symbol}"
    timeout = float(getattr(settings, "delta_public_http_timeout_seconds", 15.0) or 15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid product response")
    if not data.get("success", True) and not data.get("result"):
        raise ValueError("Product response unsuccessful")
    result = data.get("result")
    if not isinstance(result, dict):
        raise ValueError("Missing product result")
    return result


async def get_contract_specs(symbol: str) -> ContractSpecs:
    """Return cached or live contract specs for a symbol (e.g. BTCUSD).

    Falls back to ``settings.contract_value_btc`` / ``tick_size`` on failure.
    """
    sym = (symbol or "").strip().upper() or "BTCUSD"
    default_cv = float(getattr(settings, "contract_value_btc", 0.001))
    default_tick = float(getattr(settings, "tick_size", 0.5))

    if not getattr(settings, "use_live_product_specs", True):
        return ContractSpecs(
            symbol=sym,
            contract_value_btc=default_cv,
            tick_size=default_tick,
            product_id=int(getattr(settings, "product_id", 27)),
            taker_commission_rate=float(getattr(settings, "taker_fee_rate", 0.0005)),
        )

    ttl = int(getattr(settings, "product_specs_cache_ttl_seconds", 3600) or 3600)
    cache_key = f"{CACHE_KEY_PREFIX}{sym}"
    try:
        cached = await get_cache(cache_key)
        if isinstance(cached, dict) and cached.get("contract_value_btc") is not None:
            return ContractSpecs(
                symbol=str(cached.get("symbol") or sym),
                contract_value_btc=float(cached["contract_value_btc"]),
                tick_size=float(cached.get("tick_size", default_tick)),
                product_id=int(cached.get("product_id", getattr(settings, "product_id", 27))),
                taker_commission_rate=cached.get("taker_commission_rate"),
            )
    except Exception:
        pass

    try:
        raw = await _fetch_product_public(sym)
        specs = _product_result_to_specs(sym, raw)
        try:
            await set_cache(
                cache_key,
                {
                    "symbol": specs.symbol,
                    "contract_value_btc": specs.contract_value_btc,
                    "tick_size": specs.tick_size,
                    "product_id": specs.product_id,
                    "taker_commission_rate": specs.taker_commission_rate,
                },
                ttl=ttl,
            )
        except Exception as e:
            logger.debug("product_specs_cache_set_failed", symbol=sym, error=str(e))
        return specs
    except Exception as e:
        logger.warning(
            "product_specs_fetch_failed",
            symbol=sym,
            error=str(e),
            message="Using config fallback for contract_value/tick_size",
        )
        return ContractSpecs(
            symbol=sym,
            contract_value_btc=default_cv,
            tick_size=default_tick,
            product_id=int(getattr(settings, "product_id", 27)),
            taker_commission_rate=float(getattr(settings, "taker_fee_rate", 0.0005)),
        )
