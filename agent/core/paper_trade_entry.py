"""
Shared USD/INR resolution and entry-ledger fields for paper trade audit lines.

Used by execution engine (risk-approved path) and intelligent_agent manual executes
so OPEN log lines stay consistent.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

from agent.core.config import settings
from agent.core.futures_utils import entry_leg_fees_usd
from agent.core.redis_config import get_cache


async def resolve_paper_usdinr_rate(payload_usd_inr: Optional[Any] = None) -> float:
    """Live USDINR from payload, else Redis ``fx:usdinr:last``, else config fallback."""
    if payload_usd_inr is not None:
        try:
            v = float(payload_usd_inr)
            if v > 0 and math.isfinite(v):
                return v
        except (TypeError, ValueError):
            pass
    try:
        cached = await get_cache("fx:usdinr:last")
        if isinstance(cached, dict):
            val = cached.get("rate")
            if val is not None and float(val) > 0:
                return float(val)
    except Exception:
        pass
    return float(getattr(settings, "usdinr_fallback_rate", 83.0) or 83.0)


def compute_paper_entry_ledger(
    *,
    quantity: float,
    fill_price: float,
    contract_value_btc: float,
    usd_inr_rate: float,
    entry_fee_usd: Optional[float] = None,
) -> Tuple[float, float, float]:
    """Compute TRADE| line fields: (trade_value_inr, fees_inr_open, entry_fee_usd).

    ``fees_inr_open`` is non-zero only when FEE_ACCOUNTING_MODE is ``split`` (entry leg
    at open); otherwise fees are recognized at close.
    """
    mode = (getattr(settings, "fee_accounting_mode", "split") or "split").lower()
    taker = float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005)
    slip = float(getattr(settings, "slippage_bps", 5.0) or 5.0)
    if entry_fee_usd is None:
        ef = entry_leg_fees_usd(
            float(fill_price),
            float(quantity),
            float(contract_value_btc),
            taker,
            slip,
        )
    else:
        ef = float(entry_fee_usd)
    trade_value_inr = (
        float(quantity) * float(fill_price) * float(contract_value_btc) * float(usd_inr_rate)
    )
    fees_inr_open = float(ef * usd_inr_rate) if mode == "split" else 0.0
    return trade_value_inr, fees_inr_open, ef
