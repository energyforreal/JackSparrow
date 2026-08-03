"""Fetch derivatives ticker snapshots from Delta Exchange public ticker API.

Uses a dedicated production-public base URL (``jacksparrow_v43_oi_public_base_url``)
so ticker/OI data can be read from ``api.india.delta.exchange`` while trading stays
on testnet.

Real-only policy: no synthetic backfill. Sparse ring-buffer history is returned as-is;
the feature engineer zero-fills missing columns when data is absent or flat.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd
import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_OI_FETCH_TIMEOUT_S: float = 4.0
_OI_HISTORY_INTERVAL_S: float = 300.0
_OI_HISTORY_DEFAULT_BARS: int = 300

# In-process ticker ring buffer: symbol -> chronological row dicts (capped)
_OI_RING: Dict[str, List[Dict[str, Any]]] = {}
_OI_RING_MAX: int = 1000

TICKER_RING_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "oi_contracts",
    "oi_value_usd",
    "taker_buy_ratio",
    "mark_price",
    "spot_price",
    "best_bid",
    "best_ask",
    "bid_size",
    "ask_size",
    "price_band_upper",
    "price_band_lower",
    "predicted_funding_rate",
)


def _ticker_empty_row() -> Dict[str, float]:
    return {
        "oi_contracts": 0.0,
        "oi_value_usd": 0.0,
        "taker_buy_ratio": 0.5,
        "mark_price": 0.0,
        "spot_price": 0.0,
        "best_bid": 0.0,
        "best_ask": 0.0,
        "bid_size": 0.0,
        "ask_size": 0.0,
        "price_band_upper": 0.0,
        "price_band_lower": 0.0,
        "predicted_funding_rate": 0.0,
    }


def _oi_settings() -> tuple[bool, float, str]:
    enabled = bool(getattr(settings, "jacksparrow_v43_oi_enabled", True))
    timeout = float(
        getattr(settings, "jacksparrow_v43_oi_fetch_timeout_s", _OI_FETCH_TIMEOUT_S)
        or _OI_FETCH_TIMEOUT_S
    )
    base = str(
        getattr(settings, "jacksparrow_v43_oi_public_base_url", "https://api.india.delta.exchange")
        or "https://api.india.delta.exchange"
    ).rstrip("/")
    return enabled, timeout, base


def _safe_float(val: Any, fallback: float = 0.0) -> float:
    if val is None:
        return fallback
    try:
        return float(val)
    except (TypeError, ValueError):
        return fallback


def _parse_oi_ticker(response: Any) -> Dict[str, float]:
    """Extract OI + microstructure scalars from a Delta ticker API response dict."""
    empty = _ticker_empty_row()
    if not isinstance(response, dict):
        return empty

    result: Any = response.get("result") or {}
    if not isinstance(result, dict):
        return empty

    def _float(key: str, fallback: float = 0.0) -> float:
        return _safe_float(result.get(key), fallback)

    oi = _float("oi") or _float("oi_contracts")
    oi_usd = _float("oi_value_usd") or _float("oi_value")

    tbv = result.get("taker_buy_vol")
    tsv = result.get("taker_sell_vol")
    if tbv is not None and tsv is not None:
        total = _float("taker_buy_vol") + _float("taker_sell_vol")
        taker_ratio = _float("taker_buy_vol") / total if total > 1e-9 else 0.5
    else:
        taker_ratio = 0.5

    quotes = result.get("quotes")
    if not isinstance(quotes, dict):
        quotes = {}
    price_band = result.get("price_band")
    if not isinstance(price_band, dict):
        price_band = {}

    mark_price = _float("mark_price")
    spot_price = _float("spot_price")
    best_bid = _safe_float(quotes.get("best_bid"), 0.0)
    best_ask = _safe_float(quotes.get("best_ask"), 0.0)
    bid_size = _safe_float(quotes.get("bid_size"), 0.0)
    ask_size = _safe_float(quotes.get("ask_size"), 0.0)
    band_upper = _safe_float(price_band.get("upper_limit"), 0.0)
    band_lower = _safe_float(price_band.get("lower_limit"), 0.0)

    predicted_fr = _float("predicted_funding_rate")
    if predicted_fr == 0.0:
        predicted_fr = _float("funding_rate")

    return {
        "oi_contracts": oi,
        "oi_value_usd": oi_usd,
        "taker_buy_ratio": float(min(1.0, max(0.0, taker_ratio))),
        "mark_price": mark_price,
        "spot_price": spot_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "price_band_upper": band_upper,
        "price_band_lower": band_lower,
        "predicted_funding_rate": predicted_fr,
    }


async def _fetch_ticker_public(symbol: str) -> Dict[str, Any]:
    """GET /v2/tickers/{symbol} from the configured OI public base URL."""
    enabled, timeout, base = _oi_settings()
    if not enabled:
        return {"success": False, "result": {}}

    url = f"{base}/v2/tickers/{symbol}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


async def fetch_oi_snapshot(
    delta_client: Any,
    symbol: str,
) -> Dict[str, float]:
    """Fetch a single ticker snapshot for ``symbol``.

    ``delta_client`` is accepted for API compatibility but ticker uses the dedicated
    public ticker endpoint (production India host by default).
    """
    _ = delta_client
    enabled, timeout, _base = _oi_settings()
    if not enabled:
        return _ticker_empty_row()

    try:
        resp = await asyncio.wait_for(_fetch_ticker_public(symbol), timeout=timeout)
        return _parse_oi_ticker(resp)
    except asyncio.TimeoutError:
        logger.warning("v43_oi_snapshot_timeout", symbol=symbol)
    except Exception as exc:
        logger.warning("v43_oi_snapshot_failed", symbol=symbol, error=str(exc))
    return _ticker_empty_row()


def _oi_ring_buffer_push(symbol: str, row: Dict[str, Any]) -> None:
    buf = _OI_RING.setdefault(symbol, [])
    ts = row.get("timestamp")
    if buf and ts is not None and buf[-1].get("timestamp") == ts:
        buf[-1] = {**buf[-1], **row}
        return
    buf.append(row)
    if len(buf) > _OI_RING_MAX:
        del buf[0]


def _oi_ring_buffer_get(symbol: str, n: int) -> List[Dict[str, Any]]:
    buf = _OI_RING.get(symbol, [])
    if not buf:
        return []
    return list(buf[-n:])


def clear_oi_ring_buffer(symbol: Optional[str] = None) -> None:
    """Clear the in-process ticker ring buffer (primarily for tests)."""
    if symbol:
        _OI_RING.pop(symbol, None)
    else:
        _OI_RING.clear()


def load_oi_ring_buffer_from_records(symbol: str, records: List[Dict[str, Any]]) -> int:
    """Load historical ticker rows into the ring buffer (e.g. from CSV export)."""
    sym = str(symbol or "").strip().upper()
    if not sym or not records:
        return 0
    clear_oi_ring_buffer(sym)
    for row in records:
        if not isinstance(row, dict):
            continue
        _oi_ring_buffer_push(sym, dict(row))
    return len(_OI_RING.get(sym, []))


async def fetch_oi_history(
    delta_client: Any,
    symbol: str,
    n_snapshots: int = _OI_HISTORY_DEFAULT_BARS,
) -> pd.DataFrame:
    """Return real ticker snapshot history from ring buffer + current ticker.

    Does not synthesize or constant-fill missing bars. When history is sparse,
    the returned frame may be shorter than ``n_snapshots``.
    """
    empty_cols = list(TICKER_RING_COLUMNS)
    enabled, _, _ = _oi_settings()
    if not enabled:
        return pd.DataFrame(columns=empty_cols)

    snapshot = await fetch_oi_snapshot(delta_client, symbol)
    now_epoch = int(time.time())
    bar_s = int(_OI_HISTORY_INTERVAL_S)
    latest_bar = (now_epoch // bar_s) * bar_s

    rows = _oi_ring_buffer_get(symbol, n_snapshots)
    has_data = (
        snapshot.get("oi_contracts", 0) > 0
        or snapshot.get("oi_value_usd", 0) > 0
        or snapshot.get("mark_price", 0) > 0
        or snapshot.get("spot_price", 0) > 0
    )
    if rows:
        rows = list(rows)
        rows[-1] = {**rows[-1], **snapshot, "timestamp": latest_bar}
    elif has_data:
        rows = [{**snapshot, "timestamp": latest_bar}]
    else:
        return pd.DataFrame(columns=empty_cols)

    _oi_ring_buffer_push(symbol, {**snapshot, "timestamp": latest_bar})

    df = pd.DataFrame(rows[-n_snapshots:])
    for col in empty_cols:
        if col not in df.columns:
            df[col] = 0.5 if col == "taker_buy_ratio" else 0.0
    return df[empty_cols].reset_index(drop=True)


def export_oi_ring_buffer(symbol: str) -> List[Dict[str, Any]]:
    """Export ring-buffer rows for a symbol (training / persistence)."""
    return list(_OI_RING.get(str(symbol or "").strip().upper(), []))
