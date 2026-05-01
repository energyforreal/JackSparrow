"""
Exchange gateway abstraction for live/paper Delta-compatible private APIs.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional

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
        return await self._delta_client.get_positions(product_symbol=symbol)

    async def get_margined_positions(self) -> Dict[str, Any]:
        return await self._delta_client.get_margined_positions()

    async def get_assets(self) -> Dict[str, Any]:
        return await self._delta_client.get_assets()

    async def change_margin(self, product_symbol: str, margin: float) -> Dict[str, Any]:
        return await self._delta_client.change_margin(product_symbol=product_symbol, margin=margin)

    async def close_all_positions(self) -> Dict[str, Any]:
        return await self._delta_client.close_all_positions()


class PaperExchangeStateStore:
    """In-memory state for Delta-compatible paper private endpoint projections."""

    def __init__(self, margined_view_delay_seconds: float = 10.0):
        self._margin_overrides_usd: Dict[str, float] = {}
        self._realized_pnl_usd: Dict[str, float] = {}
        self._realized_funding_usd: Dict[str, float] = {}
        self._adl_level: Dict[str, int] = {}
        self._margined_snapshot: List[Dict[str, Any]] = []
        self._margined_snapshot_at: float = 0.0
        self._margined_view_delay_seconds = max(0.0, float(margined_view_delay_seconds))

    def register_open_position(self, symbol: str, margin_usd: float, adl_level: int = 1) -> None:
        self._margin_overrides_usd[symbol] = max(0.0, float(margin_usd))
        self._adl_level[symbol] = int(adl_level)
        self._margined_snapshot_at = 0.0

    def register_closed_position(
        self,
        symbol: str,
        realized_pnl_usd: float,
        realized_funding_usd: float = 0.0,
    ) -> None:
        self._realized_pnl_usd[symbol] = float(self._realized_pnl_usd.get(symbol, 0.0)) + float(
            realized_pnl_usd
        )
        self._realized_funding_usd[symbol] = float(
            self._realized_funding_usd.get(symbol, 0.0)
        ) + float(realized_funding_usd)
        self._margin_overrides_usd.pop(symbol, None)
        self._margined_snapshot_at = 0.0

    def adjust_margin(self, symbol: str, margin_delta_usd: float, current_margin_usd: float) -> float:
        baseline = self._margin_overrides_usd.get(symbol, current_margin_usd)
        updated = max(0.0, float(baseline) + float(margin_delta_usd))
        self._margin_overrides_usd[symbol] = updated
        self._margined_snapshot_at = 0.0
        return updated

    def get_realized_pnl(self, symbol: str) -> float:
        return float(self._realized_pnl_usd.get(symbol, 0.0))

    def get_realized_funding(self, symbol: str) -> float:
        return float(self._realized_funding_usd.get(symbol, 0.0))

    def get_margin_override(self, symbol: str) -> Optional[float]:
        return self._margin_overrides_usd.get(symbol)

    def get_adl_level(self, symbol: str) -> int:
        return int(self._adl_level.get(symbol, 1))

    def should_refresh_margined_snapshot(self) -> bool:
        if self._margined_snapshot_at <= 0:
            return True
        return (time.time() - self._margined_snapshot_at) >= self._margined_view_delay_seconds

    def set_margined_snapshot(self, snapshot: List[Dict[str, Any]]) -> None:
        self._margined_snapshot = snapshot
        self._margined_snapshot_at = time.time()

    def get_margined_snapshot(self) -> List[Dict[str, Any]]:
        return list(self._margined_snapshot)


class DeltaPaperSimExchangeGateway(ExchangeGateway):
    """Paper gateway that projects internal positions as Delta private API payloads."""

    def __init__(
        self,
        *,
        position_reader: Callable[[], Dict[str, Dict[str, Any]]],
        close_position_cb: Callable[[str], Awaitable[Any]],
        margined_view_delay_seconds: float = 10.0,
    ):
        self._position_reader = position_reader
        self._close_position_cb = close_position_cb
        self._state = PaperExchangeStateStore(
            margined_view_delay_seconds=margined_view_delay_seconds
        )

    @staticmethod
    def _signed_size(position: Dict[str, Any]) -> float:
        lots = float(position.get("lots", position.get("quantity", 0.0)) or 0.0)
        return lots if position.get("side") == "long" else -lots

    @staticmethod
    def _liquidation_price(entry_price: float, side: str, leverage: int, maintenance_frac: float) -> float:
        if leverage <= 0 or entry_price <= 0:
            return entry_price
        delta = (1.0 - maintenance_frac) / leverage
        if side == "long":
            return max(0.0, entry_price * (1.0 - delta))
        return entry_price * (1.0 + delta)

    def _build_delta_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(position.get("symbol"))
        entry_price = float(position.get("entry_price", 0.0) or 0.0)
        leverage = max(1, int(getattr(settings, "isolated_margin_leverage", 5) or 5))
        cv = float(position.get("contract_value_btc") or getattr(settings, "contract_value_btc", 0.001))
        lots = abs(float(position.get("lots", position.get("quantity", 0.0)) or 0.0))
        notional_usd = entry_price * lots * cv
        base_margin = notional_usd / leverage if leverage > 0 else 0.0
        margin = float(self._state.get_margin_override(symbol) or base_margin)
        maintenance_frac = float(getattr(settings, "maintenance_fraction_of_initial", 0.5) or 0.5)
        side = str(position.get("side") or "long").lower()
        liq_price = self._liquidation_price(entry_price, side, leverage, maintenance_frac)

        return {
            "product_symbol": symbol,
            "size": self._signed_size(position),
            "entry_price": entry_price,
            "margin": margin,
            "liquidation_price": liq_price,
            "realized_pnl": self._state.get_realized_pnl(symbol),
            "realized_funding": self._state.get_realized_funding(symbol),
            "adl_level": self._state.get_adl_level(symbol),
            "unrealized_pnl": float(position.get("unrealized_pnl", 0.0) or 0.0),
            "mark_price": float(position.get("current_price", entry_price) or entry_price),
            "side": side,
        }

    async def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        all_positions = self._position_reader()
        records = []
        for sym, pos in all_positions.items():
            if symbol and sym != symbol:
                continue
            records.append(self._build_delta_position(pos))
        return {"success": True, "result": records}

    async def get_margined_positions(self) -> Dict[str, Any]:
        if self._state.should_refresh_margined_snapshot():
            current = await self.get_positions()
            self._state.set_margined_snapshot(list(current.get("result", [])))
        return {"success": True, "result": self._state.get_margined_snapshot()}

    async def get_assets(self) -> Dict[str, Any]:
        base_symbol = str(getattr(settings, "trading_symbol", "BTCUSD") or "BTCUSD")
        asset_code = "".join([ch for ch in base_symbol if ch.isalpha()])[:3] or "BTC"
        return {
            "success": True,
            "result": [
                {
                    "symbol": asset_code.upper(),
                    "precision": 8,
                    "is_deposit_enabled": False,
                    "is_withdrawal_enabled": False,
                    "status": "paper_simulated",
                }
            ],
        }

    async def change_margin(self, product_symbol: str, margin: float) -> Dict[str, Any]:
        open_positions = self._position_reader()
        position = open_positions.get(product_symbol)
        if not position:
            return {"success": False, "error": f"Position not found for {product_symbol}"}
        current = self._build_delta_position(position)
        updated = self._state.adjust_margin(
            symbol=product_symbol,
            margin_delta_usd=float(margin),
            current_margin_usd=float(current.get("margin", 0.0) or 0.0),
        )
        logger.info(
            "paper_sim_margin_changed",
            symbol=product_symbol,
            margin_delta=float(margin),
            updated_margin=updated,
        )
        return {"success": True, "result": {"product_symbol": product_symbol, "margin": updated}}

    async def close_all_positions(self) -> Dict[str, Any]:
        open_positions = list(self._position_reader().keys())
        if not open_positions:
            return {"success": True, "result": {"closed_symbols": []}}
        closed: List[str] = []
        failed: Dict[str, str] = {}
        for symbol in open_positions:
            try:
                result = await self._close_position_cb(symbol)
                if bool(getattr(result, "success", False)):
                    closed.append(symbol)
                else:
                    failed[symbol] = str(getattr(result, "error_message", "close_failed"))
            except Exception as e:
                failed[symbol] = str(e)
        return {"success": len(failed) == 0, "result": {"closed_symbols": closed, "failed": failed}}

    def register_position_opened(self, position: Dict[str, Any]) -> None:
        symbol = str(position.get("symbol"))
        if not symbol:
            return
        margin = float(position.get("margin", 0.0) or 0.0)
        if margin <= 0:
            entry_price = float(position.get("entry_price", 0.0) or 0.0)
            lots = abs(float(position.get("lots", position.get("quantity", 0.0)) or 0.0))
            cv = float(
                position.get("contract_value_btc") or getattr(settings, "contract_value_btc", 0.001)
            )
            lev = max(1, int(getattr(settings, "isolated_margin_leverage", 5) or 5))
            margin = (entry_price * lots * cv) / lev if lev > 0 else 0.0
        self._state.register_open_position(symbol=symbol, margin_usd=margin)

    def register_position_closed(self, symbol: str, realized_pnl_usd: float) -> None:
        self._state.register_closed_position(symbol=symbol, realized_pnl_usd=realized_pnl_usd)


def build_exchange_gateway(
    *,
    delta_client: Any,
    position_reader: Callable[[], Dict[str, Dict[str, Any]]],
    close_position_cb: Callable[[str], Awaitable[Any]],
) -> ExchangeGateway:
    """Construct exchange gateway from config flags."""
    backend = str(getattr(settings, "exchange_backend", "delta_paper_sim") or "delta_paper_sim").lower()
    paper_mode = bool(getattr(settings, "paper_trading_mode", True))
    if paper_mode:
        return DeltaPaperSimExchangeGateway(
            position_reader=position_reader,
            close_position_cb=close_position_cb,
            margined_view_delay_seconds=float(
                getattr(settings, "paper_margined_view_delay_seconds", 10.0) or 10.0
            ),
        )
    if backend == "delta_paper_sim":
        logger.warning(
            "exchange_backend_paper_sim_ignored_in_live_mode",
            backend=backend,
            trading_mode=getattr(settings, "trading_mode", "live"),
            message="Live mode forces Delta live adapter.",
        )
    return DeltaLiveExchangeGateway(delta_client)
