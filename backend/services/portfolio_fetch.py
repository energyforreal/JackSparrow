"""Shared portfolio fetch helpers for REST and WebSocket handlers."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.services.portfolio_service import portfolio_service
from backend.services.testnet_portfolio_service import (
    TestnetExchangeUnavailableError,
    testnet_portfolio_service,
)

__all__ = [
    "TestnetExchangeUnavailableError",
    "RECENT_TRADES_SUPPRESS_KEY",
    "clear_recent_trades_display",
    "fetch_portfolio_summary",
    "fetch_recent_closed_trades",
    "is_testnet_trading_mode",
    "require_testnet_exchange",
]

RECENT_TRADES_SUPPRESS_KEY = "portfolio:recent_trades_suppressed"
_RECENT_TRADES_SUPPRESS_FILE = (
    Path(__file__).resolve().parents[2] / "data" / ".suppress_recent_trades"
)


def is_recent_trades_suppressed() -> bool:
    """True when recent-trades display was cleared (file flag or env)."""
    import os

    if _RECENT_TRADES_SUPPRESS_FILE.is_file():
        return True
    return os.environ.get("SUPPRESS_RECENT_TRADES", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def set_recent_trades_suppressed(suppressed: bool = True) -> None:
    """Persist suppress flag on disk (works without Redis)."""
    if suppressed:
        _RECENT_TRADES_SUPPRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_TRADES_SUPPRESS_FILE.write_text("1", encoding="utf-8")
    elif _RECENT_TRADES_SUPPRESS_FILE.is_file():
        _RECENT_TRADES_SUPPRESS_FILE.unlink()


def is_testnet_trading_mode() -> bool:
    return str(getattr(settings, "trading_mode", "testnet")).lower() == "testnet"


async def require_testnet_exchange() -> None:
    """Raise TestnetExchangeUnavailableError when Delta testnet is unreachable."""
    if not is_testnet_trading_mode():
        return
    available = await testnet_portfolio_service.is_exchange_available()
    if not available:
        raise TestnetExchangeUnavailableError()


async def fetch_portfolio_summary(db: AsyncSession) -> Optional[Dict[str, Any]]:
    if is_testnet_trading_mode():
        return await testnet_portfolio_service.get_portfolio_summary(db)
    return await portfolio_service.get_portfolio_summary(db)


async def clear_recent_trades_display() -> bool:
    """Hide recent trades in API/WS (local DB + suppress exchange history in UI)."""
    from backend.core.database import AsyncSessionLocal
    from backend.core.redis import delete_cache, set_cache
    from backend.services.agent_trade_ledger_service import clear_agent_trade_ledger

    async with AsyncSessionLocal() as session:
        await portfolio_service.delete_all_trades_and_positions(session)
        await session.commit()

    await clear_agent_trade_ledger()
    set_recent_trades_suppressed(True)
    redis_ok = True
    try:
        redis_ok = await set_cache(RECENT_TRADES_SUPPRESS_KEY, True, ttl=86400 * 365)
        await delete_cache("portfolio:summary")
        await delete_cache("portfolio:testnet:summary")
    except Exception:
        redis_ok = False
    return redis_ok


async def fetch_recent_closed_trades(
    db: AsyncSession,
    *,
    symbol: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    if is_recent_trades_suppressed():
        return []

    from backend.core.redis import get_cache

    try:
        if await get_cache(RECENT_TRADES_SUPPRESS_KEY):
            return []
    except Exception:
        pass

    if is_testnet_trading_mode():
        from backend.services.agent_trade_ledger_service import get_agent_closed_trades

        rows = await get_agent_closed_trades(
            symbol=symbol,
            limit=limit,
            offset=offset,
        )
        return rows
    return await portfolio_service.get_recent_closed_trades(
        db=db,
        symbol=symbol,
        limit=limit,
        offset=offset,
    )
