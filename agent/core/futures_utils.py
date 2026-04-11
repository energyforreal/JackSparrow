"""
futures_utils.py
Core calculation utilities for perpetual futures trading.

Canonical semantics:
- ``quantity`` / ``lots`` in the agent and DB are **contract lot counts** (integers).
- **USD notional** for a position is ``lots * btc_price_usd * contract_value_btc``.
- **USD PnL** is ``lots * (exit_price - entry_price) * contract_value_btc`` for long,
  with the sign inverted for short. Always multiply by ``contract_value_btc``; do not
  treat ``lots * price`` as notional without ``contract_value_btc``.
"""
import math
from typing import Literal

Side = Literal["long", "short"]


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


def gross_pnl_usd(
    entry_price: float,
    exit_price: float,
    lots: float,
    side: str,
    contract_value_btc: float = 0.001,
) -> float:
    """Price PnL in USD before fees (long: profit when exit > entry)."""
    delta = (exit_price - entry_price) * float(lots) * contract_value_btc
    s = (side or "").lower()
    if s in ("short", "sell"):
        return -delta
    return delta


def unrealized_pnl_usd(
    entry_price: float,
    mark_price: float,
    lots: float,
    side: str,
    contract_value_btc: float = 0.001,
) -> float:
    """Unrealized PnL in USD using mark (or best bid/ask mid)."""
    return gross_pnl_usd(entry_price, mark_price, lots, side, contract_value_btc)


def per_leg_cost_rate(taker_fee_rate: float, slippage_bps: float) -> float:
    """One-way cost as fraction of notional (taker + slippage)."""
    return float(taker_fee_rate) + float(slippage_bps) / 10000.0


def round_trip_fees_usd(
    entry_price: float,
    exit_price: float,
    lots: float,
    contract_value_btc: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> float:
    """Entry fee on entry notional + exit fee on exit notional (both legs)."""
    leg = per_leg_cost_rate(taker_fee_rate, slippage_bps)
    lf = float(lots)
    n_in = lf * entry_price * contract_value_btc
    n_out = lf * exit_price * contract_value_btc
    return n_in * leg + n_out * leg


def net_pnl_usd_after_fees(
    entry_price: float,
    exit_price: float,
    lots: float,
    side: str,
    contract_value_btc: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> tuple[float, float, float]:
    """Returns (gross_pnl_usd, fees_usd, net_pnl_usd)."""
    g = gross_pnl_usd(entry_price, exit_price, lots, side, contract_value_btc)
    fees = round_trip_fees_usd(
        entry_price, exit_price, lots, contract_value_btc, taker_fee_rate, slippage_bps
    )
    return g, fees, g - fees


def entry_leg_fees_usd(
    entry_price: float,
    lots: float,
    contract_value_btc: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> float:
    """One-way cost on entry notional (taker + slippage)."""
    n_in = float(lots) * float(entry_price) * contract_value_btc
    return n_in * per_leg_cost_rate(taker_fee_rate, slippage_bps)


def exit_leg_fees_usd(
    exit_price: float,
    lots: float,
    contract_value_btc: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> float:
    """One-way cost on exit notional (taker + slippage)."""
    n_out = float(lots) * float(exit_price) * contract_value_btc
    return n_out * per_leg_cost_rate(taker_fee_rate, slippage_bps)


def net_pnl_usd_after_fees_split_legs(
    entry_price: float,
    exit_price: float,
    lots: float,
    side: str,
    contract_value_btc: float,
    taker_fee_rate: float,
    slippage_bps: float,
) -> tuple[float, float, float, float, float]:
    """Returns (gross, fees_entry, fees_exit, fees_total, net).

    Same economic net as round-trip; splits fees per leg for logging.
    """
    g = gross_pnl_usd(entry_price, exit_price, lots, side, contract_value_btc)
    fe = entry_leg_fees_usd(
        entry_price, lots, contract_value_btc, taker_fee_rate, slippage_bps
    )
    fx = exit_leg_fees_usd(
        exit_price, lots, contract_value_btc, taker_fee_rate, slippage_bps
    )
    total = fe + fx
    return g, fe, fx, total, g - total


def isolated_equity_usd(
    initial_margin_usd: float,
    unrealized_pnl_usd: float,
) -> float:
    """Equity in isolated margin model (margin balance + mark PnL)."""
    return float(initial_margin_usd) + float(unrealized_pnl_usd)


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


def margin_required_inr(
    lots: int,
    btc_price_usd: float,
    usdinr_rate: float,
    leverage: int = 5,
    contract_value_btc: float = 0.001,
) -> float:
    """Estimate isolated margin requirement in INR for a lot-based BTCUSD trade."""
    if lots <= 0 or btc_price_usd <= 0 or usdinr_rate <= 0 or leverage <= 0:
        return 0.0
    notional_usd = notional_value(lots, btc_price_usd, contract_value_btc)
    margin_usd = notional_usd / leverage
    return margin_usd * usdinr_rate
