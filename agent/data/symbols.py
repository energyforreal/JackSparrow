"""Symbol helpers for Delta Exchange REST/WebSocket market data."""

from __future__ import annotations


def normalize_symbol_for_delta_api(symbol: str) -> str:
    """Strip suffixes that are not valid for Delta ticker REST/WS (e.g. TradingView ``BTCUSD.P``).

    Delta ``/v2/tickers/{symbol}`` expects contract symbols such as ``BTCUSD`` without ``.P``.
    """
    if not symbol:
        return symbol
    s = symbol.strip()
    if s.endswith(".P"):
        return s[:-2]
    return s
