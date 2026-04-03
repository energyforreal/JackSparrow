"""
futures_utils.py
Core calculation utilities for perpetual futures trading.
All position sizing returns integer lots; all prices are in USD.
"""
import math


def price_to_lots(
    usd_margin: float,
    btc_price: float,
    leverage: int = 5,
    contract_value_btc: float = 0.001,
    max_lots: int = 100,
    min_lots: int = 1,
) -> int:
    notional_usd = usd_margin * leverage
    lot_value_usd = btc_price * contract_value_btc
    if lot_value_usd <= 0:
        return 0
    raw_lots = notional_usd / lot_value_usd
    lots = max(min_lots, min(max_lots, math.floor(raw_lots)))
    return int(lots)


def notional_value(lots: int, btc_price: float,
                   contract_value_btc: float = 0.001) -> float:
    return lots * btc_price * contract_value_btc


def pct_to_price(entry_price: float, pct: float) -> float:
    return entry_price * (1 + pct)


def calculate_liquidation_price(
    entry_price: float,
    leverage: int,
    side: str,
    maintenance_margin: float = 0.0025,
) -> float:
    if side == "long":
        return entry_price * (1 - 1 / leverage + maintenance_margin)
    else:
        return entry_price * (1 + 1 / leverage - maintenance_margin)


def round_to_tick(price: float, tick_size: float = 0.50) -> float:
    if tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 2)


def fee_adjusted_pnl(
    entry_price: float,
    exit_price: float,
    lots: int,
    side: str,
    contract_value_btc: float = 0.001,
    fee_rate: float = 0.0005,
    funding_accumulated: float = 0.0,
) -> float:
    notional = notional_value(lots, entry_price, contract_value_btc)
    price_pnl = lots * (exit_price - entry_price) * contract_value_btc
    if side == "short":
        price_pnl = -price_pnl
    fees = 2 * fee_rate * notional
    net = price_pnl - fees - (funding_accumulated * notional)
    return net
