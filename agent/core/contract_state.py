"""Delta perpetual contract state for v43 policy/risk gates."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_CACHE: Dict[str, tuple[float, "ContractStateSnapshot"]] = {}


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ContractStateSnapshot:
    """Static + slow-moving contract metadata from GET /v2/products/{symbol}."""

    symbol: str
    state: str
    trading_status: str
    only_reduce_only_orders_allowed: bool
    maintenance_margin: float
    initial_margin: float
    max_leverage_notional: float
    impact_size: float
    price_band_pct: float
    mark_price: float = 0.0
    price_band_upper: float = 0.0
    price_band_lower: float = 0.0

    @property
    def is_operational(self) -> bool:
        return (
            str(self.state or "").lower() == "live"
            and str(self.trading_status or "").lower() == "operational"
            and not self.only_reduce_only_orders_allowed
        )

    def dist_to_upper_band_pct(self) -> float:
        if self.mark_price <= 0 or self.price_band_upper <= 0:
            return 999.0
        return max(0.0, (self.price_band_upper - self.mark_price) / self.mark_price * 100.0)

    def dist_to_lower_band_pct(self) -> float:
        if self.mark_price <= 0 or self.price_band_lower <= 0:
            return 999.0
        return max(0.0, (self.mark_price - self.price_band_lower) / self.mark_price * 100.0)


def _default_snapshot(symbol: str) -> ContractStateSnapshot:
    return ContractStateSnapshot(
        symbol=str(symbol or "BTCUSD").upper(),
        state="live",
        trading_status="operational",
        only_reduce_only_orders_allowed=False,
        maintenance_margin=0.25,
        initial_margin=0.5,
        max_leverage_notional=100000.0,
        impact_size=10000.0,
        price_band_pct=2.5,
    )


def _parse_product_result(symbol: str, result: Dict[str, Any]) -> ContractStateSnapshot:
    sym = str(result.get("symbol") or symbol).upper()
    specs = result.get("product_specs")
    if not isinstance(specs, dict):
        specs = {}
    return ContractStateSnapshot(
        symbol=sym,
        state=str(result.get("state") or "live"),
        trading_status=str(result.get("trading_status") or "operational"),
        only_reduce_only_orders_allowed=bool(specs.get("only_reduce_only_orders_allowed", False)),
        maintenance_margin=_safe_float(result.get("maintenance_margin"), 0.25),
        initial_margin=_safe_float(result.get("initial_margin"), 0.5),
        max_leverage_notional=_safe_float(result.get("max_leverage_notional"), 100000.0),
        impact_size=_safe_float(result.get("impact_size"), 10000.0),
        price_band_pct=_safe_float(result.get("price_band"), 2.5),
    )


async def _fetch_product_public(symbol: str) -> Dict[str, Any]:
    base = str(
        getattr(settings, "jacksparrow_v43_oi_public_base_url", "https://api.india.delta.exchange")
        or "https://api.india.delta.exchange"
    ).rstrip("/")
    url = f"{base}/v2/products/{symbol}"
    timeout = float(getattr(settings, "jacksparrow_v43_oi_fetch_timeout_s", 4.0) or 4.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid product response")
    result = data.get("result")
    if not isinstance(result, dict):
        raise ValueError("Missing product result")
    return result


def enrich_contract_state_from_ticker(
    state: ContractStateSnapshot,
    ticker_row: Optional[Dict[str, Any]],
) -> ContractStateSnapshot:
    """Attach live mark/band fields from the latest ticker snapshot."""
    if not ticker_row:
        return state
    mark = _safe_float(ticker_row.get("mark_price"), state.mark_price)
    upper = _safe_float(ticker_row.get("price_band_upper"), state.price_band_upper)
    lower = _safe_float(ticker_row.get("price_band_lower"), state.price_band_lower)
    return ContractStateSnapshot(
        symbol=state.symbol,
        state=state.state,
        trading_status=state.trading_status,
        only_reduce_only_orders_allowed=state.only_reduce_only_orders_allowed,
        maintenance_margin=state.maintenance_margin,
        initial_margin=state.initial_margin,
        max_leverage_notional=state.max_leverage_notional,
        impact_size=state.impact_size,
        price_band_pct=state.price_band_pct,
        mark_price=mark,
        price_band_upper=upper,
        price_band_lower=lower,
    )


async def get_contract_state(
    symbol: str,
    *,
    ticker_row: Optional[Dict[str, Any]] = None,
) -> ContractStateSnapshot:
    """Return cached or live contract state for policy/risk gates."""
    sym = str(symbol or "").strip().upper() or "BTCUSD"
    ttl = float(getattr(settings, "jacksparrow_v43_contract_state_ttl_s", 60.0) or 60.0)
    now = time.time()
    cached = _CACHE.get(sym)
    if cached and (now - cached[0]) < ttl:
        snap = enrich_contract_state_from_ticker(cached[1], ticker_row)
        if ticker_row:
            _CACHE[sym] = (now, snap)
        return snap

    try:
        result = await _fetch_product_public(sym)
        snap = _parse_product_result(sym, result)
    except Exception as exc:
        logger.warning("v43_contract_state_fetch_failed", symbol=sym, error=str(exc))
        snap = _default_snapshot(sym)

    snap = enrich_contract_state_from_ticker(snap, ticker_row)
    _CACHE[sym] = (now, snap)
    return snap


def clear_contract_state_cache(symbol: Optional[str] = None) -> None:
    """Clear in-process contract state cache (tests)."""
    if symbol:
        _CACHE.pop(str(symbol).strip().upper(), None)
    else:
        _CACHE.clear()
