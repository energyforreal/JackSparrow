"""
Trading event handler.

Bridges DecisionReadyEvent to RiskApprovedEvent by performing risk validation
and publishing RiskApprovedEvent when trades are approved.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog

from agent.events.schemas import DecisionReadyEvent, RiskApprovedEvent, EventType
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager
from agent.core.config import settings

logger = structlog.get_logger()


class TradingEventHandler:
    """Handler that bridges DecisionReadyEvent to RiskApprovedEvent."""

    def __init__(self, risk_manager, delta_client=None):
        """Initialize trading event handler.

        Args:
            risk_manager: RiskManager instance for trade validation
            delta_client: DeltaExchangeClient for fetching live market prices (required for paper trading)
        """
        self.risk_manager = risk_manager
        self.context_manager = context_manager
        self.delta_client = delta_client

    async def handle_decision_ready_for_trading(self, event: DecisionReadyEvent):
        """Handle decision ready event - validate risk and publish RiskApprovedEvent if approved.

        For BUY/SELL signals, performs risk validation and publishes RiskApprovedEvent
        to trigger trade execution. Skips HOLD signals.

        Args:
            event: Decision ready event with signal, confidence, position_size
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol", settings.trading_symbol or "BTCUSD")
            signal = payload.get("signal")
            confidence = payload.get("confidence", 0.0)
            position_size = payload.get("position_size", 0.0)

            # Skip HOLD - no trade to execute
            if signal == "HOLD" or not signal:
                logger.debug(
                    "trading_handler_skipping_hold",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                )
                return

            # Map signal to side (BUY/SELL for event, long/short for risk manager)
            if signal in ("BUY", "STRONG_BUY"):
                side = "BUY"
                risk_side = "long"
            elif signal in ("SELL", "STRONG_SELL"):
                side = "SELL"
                risk_side = "short"
            else:
                logger.debug(
                    "trading_handler_skipping_non_trade_signal",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                )
                return

            # Check confidence threshold
            if confidence < settings.min_confidence_threshold:
                logger.info(
                    "trading_handler_confidence_below_threshold",
                    symbol=symbol,
                    signal=signal,
                    confidence=confidence,
                    threshold=settings.min_confidence_threshold,
                    event_id=event.event_id,
                )
                return

            # Get portfolio value and current price from live market data
            state = self.context_manager.get_state()
            portfolio_value = (
                state.portfolio_value if state else settings.initial_balance
            )
            entry_price = await self._get_current_price(symbol, state)
            if entry_price is None or entry_price <= 0:
                logger.warning(
                    "trading_handler_no_price_available",
                    symbol=symbol,
                    event_id=event.event_id,
                    message="Skipping trade: no valid market price available",
                )
                return

            # Ensure position_size is within bounds
            proposed_size = max(0.01, min(position_size or 0.05, settings.max_position_size))

            # Validate trade with risk manager
            validation = await self.risk_manager.validate_trade(
                symbol=symbol,
                side=risk_side,
                proposed_size=proposed_size,
                entry_price=entry_price,
                stop_loss=None,  # Execution will compute from config
            )

            if not validation.get("approved", False):
                logger.info(
                    "trading_handler_risk_rejected",
                    symbol=symbol,
                    side=side,
                    reason=validation.get("reason", "Unknown"),
                    event_id=event.event_id,
                )
                return

            adjusted_size = validation.get("adjusted_size", proposed_size)
            quantity_dollars = adjusted_size * portfolio_value
            quantity = quantity_dollars / entry_price if entry_price > 0 else 0

            if quantity <= 0:
                logger.warning(
                    "trading_handler_zero_quantity",
                    symbol=symbol,
                    entry_price=entry_price,
                    quantity_dollars=quantity_dollars,
                    event_id=event.event_id,
                )
                return

            # Publish RiskApprovedEvent to trigger execution
            risk_approved = RiskApprovedEvent(
                source="trading_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": entry_price,
                    "risk_score": 0.8,
                    "timestamp": datetime.now(timezone.utc),
                    "reasoning_chain_id": (payload.get("reasoning_chain") or {}).get("chain_id"),
                    "confidence": confidence,
                },
            )
            await event_bus.publish(risk_approved)

            logger.info(
                "trading_handler_risk_approved_published",
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                event_id=event.event_id,
            )

        except Exception as e:
            logger.error(
                "trading_handler_decision_ready_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True,
            )

    async def _get_current_price(self, symbol: str, state: Optional[Any]) -> Optional[float]:
        """Get current price from context or live ticker. Returns None if unavailable."""
        try:
            if state and hasattr(state, "config") and state.config:
                market_data = state.config.get("market_data", {})
                if isinstance(market_data, dict) and market_data.get("price"):
                    return float(market_data["price"])
            if state and hasattr(state, "market_data") and state.market_data:
                md = state.market_data
                if isinstance(md, dict) and md.get("price"):
                    return float(md["price"])
        except (TypeError, ValueError):
            pass
        if self.delta_client:
            try:
                ticker = await self.delta_client.get_ticker(symbol)
                result = ticker.get("result") or ticker
                if isinstance(result, dict):
                    close = result.get("close") or result.get("mark_price")
                    if close is not None:
                        return float(close)
            except Exception as e:
                logger.debug(
                    "trading_handler_ticker_failed",
                    symbol=symbol,
                    error=str(e),
                )
        return None

    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(
            EventType.DECISION_READY,
            self.handle_decision_ready_for_trading,
        )
        logger.info("trading_handlers_registered")
