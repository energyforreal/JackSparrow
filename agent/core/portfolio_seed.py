"""Seed in-memory risk portfolio book from live exchange wallet snapshot."""

from __future__ import annotations

from typing import Any, Optional

import structlog

from agent.core.fx_rate import resolve_usdinr_rate

logger = structlog.get_logger()


def _wallet_equity_usd(wallet_payload: Any) -> float:
    if not isinstance(wallet_payload, dict):
        return 0.0
    meta = wallet_payload.get("meta")
    if isinstance(meta, dict):
        try:
            net = float(meta.get("net_equity") or 0.0)
            if net > 0:
                return net
        except (TypeError, ValueError):
            pass
    rows = wallet_payload.get("result")
    if isinstance(rows, dict):
        rows = rows.get("balances") or [rows]
    if not isinstance(rows, list):
        return 0.0
    total = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("asset_symbol") or row.get("symbol") or "").upper()
        if sym not in ("USD", "USDT", "USDC"):
            continue
        try:
            total += float(row.get("balance") or row.get("total_balance") or 0.0)
        except (TypeError, ValueError):
            continue
    return max(0.0, total)


async def seed_risk_manager_portfolio_from_exchange(
    execution_module: Any,
    risk_manager: Any,
    symbol: str,
) -> Optional[float]:
    """Set ``risk_manager.portfolio`` cash/book equity (USD) from exchange wallet when possible."""
    if execution_module is None or risk_manager is None:
        return None
    portfolio = getattr(risk_manager, "portfolio", None)
    if portfolio is None:
        return None
    try:
        snapshot = await execution_module.get_exchange_portfolio_snapshot(symbol=symbol)
    except Exception as exc:
        logger.warning(
            "portfolio_seed_exchange_snapshot_failed",
            symbol=symbol,
            error=str(exc),
        )
        return None
    if not isinstance(snapshot, dict):
        return None
    wallet = snapshot.get("wallet_balances")
    equity_usd = _wallet_equity_usd(wallet)
    if equity_usd <= 0:
        from agent.events.handlers.trading_handler import TradingEventHandler

        inr_avail = TradingEventHandler._extract_available_inr_from_snapshot(snapshot)
        if inr_avail > 0:
            usdinr = await resolve_usdinr_rate()
            if usdinr > 0:
                equity_usd = inr_avail / usdinr
    if equity_usd <= 0:
        return None
    prev = float(getattr(portfolio, "total_value", 0.0) or 0.0)
    # ``total_value`` is a read-only computed property (cash + positions).
    portfolio.cash_balance = float(equity_usd)
    if hasattr(portfolio, "_update_portfolio_value"):
        portfolio._update_portfolio_value()
    else:
        portfolio.current_portfolio_value = float(equity_usd)
        peak = float(getattr(portfolio, "peak_portfolio_value", 0.0) or 0.0)
        portfolio.peak_portfolio_value = max(peak, float(equity_usd))
    logger.info(
        "portfolio_seed_from_exchange",
        symbol=symbol,
        previous_total_value_usd=prev,
        seeded_total_value_usd=equity_usd,
        seeded_cash_balance_usd=float(getattr(portfolio, "cash_balance", equity_usd)),
    )
    return equity_usd
