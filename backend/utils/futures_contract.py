"""BTC perpetual contract math shared by portfolio and position updates.

``quantity`` on Position rows is **lot count**. USD notional is
``quantity * price_usd * contract_value_btc``.
"""

from __future__ import annotations

from backend.core.database import TradeSide


def unrealized_pnl_usd(
    entry_price: float,
    mark_price: float,
    lots: float,
    side: TradeSide | str,
    contract_value_btc: float,
) -> float:
    delta = (mark_price - entry_price) * float(lots) * contract_value_btc
    s = side.value if hasattr(side, "value") else str(side)
    if s.upper() == TradeSide.SELL.value:
        return -delta
    return delta


def isolated_margin_usd(
    entry_price: float,
    lots: float,
    contract_value_btc: float,
    leverage: int,
) -> float:
    notional = float(lots) * float(entry_price) * contract_value_btc
    return notional / max(1, int(leverage))
