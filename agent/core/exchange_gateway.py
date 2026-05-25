"""
Exchange gateway abstraction for live/paper Delta-compatible private APIs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()


class ExchangeGateway(ABC):
    """Uniform interface for exchange private-account operations."""

    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Return Delta-like real-time position payload."""

    @abstractmethod
    async def get_margined_positions(self) -> Dict[str, Any]:
        """Return Delta-like margined positions payload."""

    @abstractmethod
    async def get_assets(self) -> Dict[str, Any]:
        """Return Delta-like assets payload."""

    @abstractmethod
    async def get_wallet_balances(self) -> Dict[str, Any]:
        """Return Delta-like wallet balances payload."""

    @abstractmethod
    async def change_margin(self, product_symbol: str, margin: float) -> Dict[str, Any]:
        """Apply a margin adjustment for a position."""

    @abstractmethod
    async def close_all_positions(self) -> Dict[str, Any]:
        """Flatten all open positions."""


class DeltaLiveExchangeGateway(ExchangeGateway):
    """Live gateway wrapper over DeltaExchangeClient private endpoints."""

    def __init__(self, delta_client: Any):
        self._delta_client = delta_client

    async def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol:
            product_id = await self._delta_client.resolve_product_id(symbol)
            return await self._delta_client.get_positions(product_id=product_id)
        return await self._delta_client.get_margined_positions(
            contract_types="perpetual_futures"
        )

    async def get_margined_positions(self) -> Dict[str, Any]:
        return await self._delta_client.get_margined_positions(
            contract_types="perpetual_futures"
        )

    async def get_assets(self) -> Dict[str, Any]:
        return await self._delta_client.get_assets()

    async def get_wallet_balances(self) -> Dict[str, Any]:
        return await self._delta_client.get_wallet_balances()

    async def change_margin(self, product_symbol: str, margin: float) -> Dict[str, Any]:
        return await self._delta_client.change_margin(product_symbol=product_symbol, margin=margin)

    async def close_all_positions(self) -> Dict[str, Any]:
        return await self._delta_client.close_all_positions()


def build_exchange_gateway(
    *,
    delta_client: Any,
    position_reader: Callable[[], Dict[str, Dict[str, Any]]],
    close_position_cb: Callable[[str], Awaitable[Any]],
) -> ExchangeGateway:
    """Construct Delta live gateway (testnet-only runtime; paper sim removed)."""
    _ = position_reader
    _ = close_position_cb
    backend = str(getattr(settings, "exchange_backend", "delta_live") or "delta_live").lower()
    if backend != "delta_live":
        raise ValueError(f"Unsupported EXCHANGE_BACKEND={backend}; only delta_live is allowed")
    return DeltaLiveExchangeGateway(delta_client)
