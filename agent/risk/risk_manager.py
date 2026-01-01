"""Risk management service."""

from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime, date
import structlog

from agent.core.config import settings
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    DecisionReadyEvent,
    RiskAlertEvent,
    RiskApprovedEvent,
    EmergencyStopEvent,
    MarketTickEvent,
    OrderFillEvent,
    PositionClosedEvent,
    EventType
)
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class RiskManager:
    """Risk management service."""
    
    def __init__(self):
        """Initialize risk manager."""
        self.max_position_size = settings.max_position_size
        self.max_portfolio_heat = settings.max_portfolio_heat
        self.stop_loss_pct = settings.stop_loss_percentage
        self.take_profit_pct = settings.take_profit_percentage
        self.min_confidence_threshold = settings.min_confidence_threshold
        self.max_daily_loss = settings.max_daily_loss
        self.max_drawdown_limit = settings.max_drawdown
        self.max_consecutive_losses_limit = settings.max_consecutive_losses
        self.min_time_between_trades = settings.min_time_between_trades
        self.context_manager = context_manager
        self._monitoring = False
        self.daily_start_value: Optional[float] = None
        self.daily_start_date: Optional[date] = None
        self.peak_portfolio_value: Optional[float] = None
        self.daily_loss_pct: float = 0.0
        self.current_drawdown: float = 0.0
        self.consecutive_losses: int = 0
        self.last_trade_timestamp: Optional[datetime] = None
        self.pending_order: Optional[Dict[str, Any]] = None
        self.current_position: Optional[Dict[str, Any]] = None
        self.last_portfolio_value: float = settings.initial_balance
    
    async def initialize(self):
        """Initialize risk manager and register event handlers."""
        event_bus.subscribe(EventType.DECISION_READY, self._handle_decision_ready)
        event_bus.subscribe(EventType.MARKET_TICK, self._handle_market_tick)
        event_bus.subscribe(EventType.ORDER_FILL, self._handle_order_fill)
        event_bus.subscribe(EventType.POSITION_CLOSED, self._handle_position_closed)
        self._monitoring = True
    
    async def shutdown(self):
        """Shutdown risk manager."""
        self._monitoring = False
    
    async def _handle_decision_ready(self, event: DecisionReadyEvent):
        """Handle decision ready event and assess risk.
        
        Args:
            event: Decision ready event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            signal = payload.get("signal")
            position_size = payload.get("position_size", 0.0)
            confidence = payload.get("confidence", 0.0)
            exit_reason = payload.get("exit_reason")
            
            logger.info(
                "risk_manager_decision_ready_received",
                event_id=event.event_id,
                source=event.source,
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                position_size=position_size,
                exit_reason=exit_reason,
                paper_trading_mode=settings.paper_trading_mode,
                message="RiskManager received DecisionReadyEvent - starting risk assessment"
            )
            
            # Handle HOLD signals - log as paper trade entry in paper trading mode
            if signal == "HOLD":
                if settings.paper_trading_mode:
                    # In paper trading mode, log HOLD decisions as paper trade entries
                    logger.info(
                        "paper_trade_entry_hold_signal",
                        symbol=symbol,
                        signal=signal,
                        confidence=confidence,
                        position_size=position_size,
                        paper_trading_mode=settings.paper_trading_mode,
                        event_id=event.event_id,
                        message="Paper trade entry: HOLD signal - decision logged but no execution needed (low confidence/no clear opportunity)"
                    )
                else:
                    # In live trading, just log normally
                    logger.info(
                        "risk_manager_skip_hold_signal",
                        symbol=symbol,
                        confidence=confidence,
                        position_size=position_size,
                        paper_trading_mode=settings.paper_trading_mode,
                        message="DecisionReadyEvent has HOLD signal, no trade will be executed"
                    )
                return
            
            # Skip exit decisions - they are handled directly by execution module
            # Exit decisions come from risk manager itself when monitoring positions
            if exit_reason or event.source == "risk_manager":
                logger.debug(
                    "risk_manager_skip_exit_decision",
                    event_id=event.event_id,
                    exit_reason=exit_reason,
                    source=event.source,
                    message="Skipping exit decision - handled by execution module"
                )
                return

            # Enforce minimum confidence threshold
            # For paper trading, use lower threshold (50% of normal) to allow validation
            # of lower confidence signals for testing purposes
            effective_threshold = (
                self.min_confidence_threshold * 0.5
                if settings.paper_trading_mode
                else self.min_confidence_threshold
            )
            
            if confidence < effective_threshold:
                if settings.paper_trading_mode:
                    # In paper trading mode, log but don't block - allow validation
                    logger.info(
                        "paper_trade_low_confidence",
                        symbol=symbol,
                        confidence=confidence,
                        threshold=effective_threshold,
                        normal_threshold=self.min_confidence_threshold,
                        message=(
                            f"Paper trade with confidence {confidence:.2f} below normal threshold "
                            f"{self.min_confidence_threshold:.2f}, but allowing for validation "
                            f"(effective threshold: {effective_threshold:.2f})"
                        )
                    )
                    # Continue to allow trade execution for validation
                else:
                    # In live trading, block low confidence trades
                    await self._emit_risk_alert(
                        alert_type="CONFIDENCE",
                        severity="INFO",
                        message=(
                            f"Signal confidence {confidence:.2f} is below "
                            f"threshold {effective_threshold:.2f}"
                        ),
                        current_value=confidence,
                        threshold=effective_threshold,
                        symbol=symbol
                    )
                    return
            
            # Get context
            context = self.context_manager.get_current_context()
            portfolio_value = context.portfolio_value
            available_balance = context.available_balance
            current_positions = [context.position] if context.position else []
            current_price = context.current_price or 0.0
            
            logger.info(
                "risk_manager_context_loaded",
                symbol=symbol,
                portfolio_value=portfolio_value,
                available_balance=available_balance,
                current_price=current_price,
                has_existing_position=bool(context.position),
                message="Loaded context for risk assessment"
            )
            
            # Validate portfolio_value
            if portfolio_value is None or portfolio_value <= 0:
                logger.error(
                    "risk_manager_invalid_portfolio_value",
                    symbol=symbol,
                    portfolio_value=portfolio_value,
                    message="Portfolio value is zero or negative - cannot calculate quantity"
                )
                await self._emit_risk_alert(
                    alert_type="INVALID_PORTFOLIO_VALUE",
                    severity="CRITICAL",
                    message=f"Portfolio value {portfolio_value} is invalid",
                    current_value=portfolio_value or 0.0,
                    threshold=0.0,
                    symbol=symbol
                )
                return
            
            self._refresh_portfolio_metrics(context.timestamp, portfolio_value)

            # Check session-level risk guards
            if self.max_daily_loss and self.daily_loss_pct >= self.max_daily_loss:
                await self._emit_risk_alert(
                    alert_type="DAILY_LOSS",
                    severity="CRITICAL",
                    message=(
                        f"Daily loss {self.daily_loss_pct:.2%} exceeds limit {self.max_daily_loss:.2%}"
                    ),
                    current_value=self.daily_loss_pct,
                    threshold=self.max_daily_loss,
                    symbol=symbol
                )
                return

            if self.max_drawdown_limit and self.current_drawdown >= self.max_drawdown_limit:
                await self._emit_risk_alert(
                    alert_type="DRAWDOWN",
                    severity="CRITICAL",
                    message=(
                        f"Drawdown {self.current_drawdown:.2%} exceeds limit "
                        f"{self.max_drawdown_limit:.2%}"
                    ),
                    current_value=self.current_drawdown,
                    threshold=self.max_drawdown_limit,
                    symbol=symbol
                )
                return

            if (
                self.max_consecutive_losses_limit
                and self.consecutive_losses >= self.max_consecutive_losses_limit
            ):
                await self._emit_risk_alert(
                    alert_type="CONSECUTIVE_LOSSES",
                    severity="WARNING",
                    message=(
                        f"Consecutive losses {self.consecutive_losses} exceed limit "
                        f"{self.max_consecutive_losses_limit}"
                    ),
                    current_value=float(self.consecutive_losses),
                    threshold=float(self.max_consecutive_losses_limit),
                    symbol=symbol
                )
                return

            if self._cooldown_active():
                remaining = self._cooldown_seconds_remaining()
                await self._emit_risk_alert(
                    alert_type="TRADE_COOLDOWN",
                    severity="INFO",
                    message=(
                        "Cooling down between trades – "
                        f"{remaining:.0f}s remaining before next trade"
                    ),
                    current_value=remaining,
                    threshold=float(self.min_time_between_trades),
                    symbol=symbol
                )
                return
            
            # Assess risk
            risk_assessment = self.assess_risk(
                signal_strength=abs(position_size),
                portfolio_value=portfolio_value,
                available_balance=available_balance,
                current_positions=current_positions
            )
            
            logger.info(
                "risk_manager_assessment_complete",
                symbol=symbol,
                can_trade=risk_assessment.get("can_trade", False),
                portfolio_heat=risk_assessment.get("portfolio_heat", 0),
                max_portfolio_heat=self.max_portfolio_heat,
                available_balance=available_balance,
                message="Risk assessment completed"
            )
            
            if not risk_assessment.get("can_trade", False):
                # Emit risk alert
                await self._emit_risk_alert(
                    alert_type="PORTFOLIO_HEAT",
                    severity="WARNING",
                    message=f"Portfolio heat {risk_assessment.get('portfolio_heat', 0):.2%} exceeds limit",
                    current_value=risk_assessment.get("portfolio_heat", 0),
                    threshold=self.max_portfolio_heat,
                    symbol=symbol
                )
                return
            
            # Check position size
            if position_size > self.max_position_size:
                await self._emit_risk_alert(
                    alert_type="POSITION_SIZE",
                    severity="WARNING",
                    message=f"Position size {position_size:.2%} exceeds max {self.max_position_size:.2%}",
                    current_value=position_size,
                    threshold=self.max_position_size,
                    symbol=symbol
                )
                return
            
            # Calculate quantity (USD value)
            calculated_quantity = position_size * portfolio_value
            
            # Validate quantity
            if calculated_quantity <= 0:
                logger.error(
                    "risk_manager_invalid_quantity",
                    symbol=symbol,
                    position_size=position_size,
                    portfolio_value=portfolio_value,
                    calculated_quantity=calculated_quantity,
                    message="Calculated quantity is zero or negative - cannot approve trade"
                )
                await self._emit_risk_alert(
                    alert_type="INVALID_QUANTITY",
                    severity="WARNING",
                    message=f"Calculated quantity {calculated_quantity} is invalid",
                    current_value=calculated_quantity,
                    threshold=0.0,
                    symbol=symbol
                )
                return
            
            # Validate price
            if current_price <= 0:
                logger.error(
                    "risk_manager_invalid_price",
                    symbol=symbol,
                    current_price=current_price,
                    message="Current price is zero or negative - cannot approve trade"
                )
                await self._emit_risk_alert(
                    alert_type="INVALID_PRICE",
                    severity="WARNING",
                    message=f"Current price {current_price} is invalid",
                    current_value=current_price,
                    threshold=0.0,
                    symbol=symbol
                )
                return
            
            trade_side = "BUY" if signal in ["BUY", "STRONG_BUY"] else "SELL"
            
            logger.info(
                "risk_manager_approving_trade",
                symbol=symbol,
                side=trade_side,
                signal=signal,
                quantity=calculated_quantity,
                price=current_price,
                position_size=position_size,
                portfolio_value=portfolio_value,
                risk_score=1.0 - risk_assessment.get("portfolio_heat", 0),
                message="All risk checks passed - approving trade"
            )
            
            # Approve trade
            await self._emit_risk_approved(
                symbol=symbol,
                side=trade_side,
                quantity=calculated_quantity,
                price=current_price,
                risk_score=1.0 - risk_assessment.get("portfolio_heat", 0)
            )
            
        except Exception as e:
            logger.error(
                "risk_manager_decision_ready_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def _handle_market_tick(self, event: MarketTickEvent):
        """Handle market tick for continuous risk monitoring.
        
        Args:
            event: Market tick event
        """
        if not self._monitoring:
            return
        
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            current_price = payload.get("price", 0.0)
            
            # Check portfolio heat continuously
            context = self.context_manager.get_current_context()
            if not context.position:
                logger.debug(
                    "risk_manager_market_tick_no_position",
                    symbol=symbol,
                    current_price=current_price,
                    message="Received market tick but there is no open position to monitor"
                )
                return  # No position to monitor
            
            # Verify this tick is for our position symbol
            position_symbol = context.position.get("symbol")
            if position_symbol != symbol:
                logger.debug(
                    "risk_manager_market_tick_symbol_mismatch",
                    tick_symbol=symbol,
                    position_symbol=position_symbol,
                    current_price=current_price,
                    message="Market tick does not match current position symbol"
                )
                return  # Not our position symbol
            
            # Check exit conditions (stop loss / take profit)
            exit_reason = await self._check_exit_conditions(
                symbol=symbol,
                current_price=current_price,
                position=context.position
            )
            
            if exit_reason:
                logger.info(
                    "risk_manager_exit_condition_met",
                    symbol=symbol,
                    exit_reason=exit_reason,
                    current_price=current_price
                )
                # Emit exit decision
                await self._emit_exit_decision(
                    symbol=symbol,
                    exit_reason=exit_reason,
                    current_price=current_price
                )
                
        except Exception as e:
            logger.error(
                "risk_manager_market_tick_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def _handle_order_fill(self, event: OrderFillEvent):
        """Handle order fill for risk tracking.
        
        Args:
            event: Order fill event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            side = payload.get("side")
            quantity = float(payload.get("quantity", 0.0) or 0.0)
            fill_price = float(payload.get("fill_price", payload.get("price", 0.0)) or 0.0)

            pending = self.pending_order or {}
            action = pending.get("action", "open")

            if action == "close" and self.current_position:
                pnl = self._calculate_trade_pnl(fill_price)
                self._record_trade_result(pnl)
                self.current_position = None
            elif action == "scale" and self.current_position:
                self._scale_position(fill_price, quantity)
            else:
                self.current_position = {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": fill_price,
                    "quantity": quantity,
                }

            self.pending_order = None
            self._sync_risk_metrics_context()
        except Exception as e:
            logger.error(
                "risk_manager_order_fill_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
            self.pending_order = None
    
    async def _emit_risk_alert(self, alert_type: str, severity: str, message: str,
                               current_value: float, threshold: float, symbol: Optional[str] = None):
        """Emit risk alert event.
        
        Args:
            alert_type: Type of alert
            severity: Alert severity
            message: Alert message
            current_value: Current value
            threshold: Threshold value
            symbol: Optional symbol
        """
        try:
            event = RiskAlertEvent(
                source="risk_manager",
                payload={
                    "alert_type": alert_type,
                    "severity": severity,
                    "message": message,
                    "current_value": current_value,
                    "threshold": threshold,
                    "symbol": symbol,
                    "timestamp": datetime.utcnow()
                }
            )
            
            await event_bus.publish(event)
            
            # Emit emergency stop if critical
            if severity == "CRITICAL":
                await self._emit_emergency_stop(f"Risk alert: {message}")
            
            logger.warning(
                "risk_alert_emitted",
                alert_type=alert_type,
                severity=severity,
                message=message,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "risk_alert_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def _emit_risk_approved(self, symbol: str, side: str, quantity: float, price: float, risk_score: float):
        """Emit risk approved event.
        
        Args:
            symbol: Trading symbol
            side: Trade side
            quantity: Trade quantity
            price: Trade price
            risk_score: Risk score
        """
        try:
            event = RiskApprovedEvent(
                source="risk_manager",
                payload={
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "risk_score": risk_score,
                    "timestamp": datetime.utcnow()
                }
            )
            
            self._prepare_pending_order(symbol, side, quantity, price)
            await event_bus.publish(event)
            self.last_trade_timestamp = datetime.utcnow()
            self._sync_risk_metrics_context()
            
            logger.info(
                "risk_approved_emitted",
                symbol=symbol,
                side=side,
                quantity=quantity,
                risk_score=risk_score,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "risk_approved_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def _emit_emergency_stop(self, reason: str):
        """Emit emergency stop event.
        
        Args:
            reason: Reason for emergency stop
        """
        try:
            event = EmergencyStopEvent(
                source="risk_manager",
                payload={
                    "reason": reason,
                    "triggered_by": "risk_manager",
                    "timestamp": datetime.utcnow()
                }
            )
            
            await event_bus.publish(event)
            
            logger.critical(
                "emergency_stop_emitted",
                reason=reason,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "emergency_stop_emit_failed",
                error=str(e),
                exc_info=True
            )

    def _prepare_pending_order(self, symbol: str, side: str, quantity: float, price: float):
        """Track pending order details for post-trade accounting."""
        action = "open"
        if self.current_position:
            if self.current_position.get("side") == side:
                action = "scale"
            else:
                action = "close"
        self.pending_order = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "action": action,
        }

    def _calculate_trade_pnl(self, fill_price: float) -> float:
        """Calculate PnL for closing trade."""
        if not self.current_position:
            return 0.0
        entry_price = float(self.current_position.get("entry_price", fill_price) or fill_price)
        quantity = float(self.current_position.get("quantity", 0.0) or 0.0)
        if quantity <= 0:
            return 0.0
        if self.current_position.get("side") == "BUY":
            return (fill_price - entry_price) * quantity
        return (entry_price - fill_price) * quantity

    def _scale_position(self, fill_price: float, quantity: float):
        """Adjust current position when scaling in."""
        if not self.current_position:
            return
        existing_qty = float(self.current_position.get("quantity", 0.0) or 0.0)
        quantity = abs(quantity)
        total_qty = existing_qty + quantity
        if total_qty <= 0:
            return
        weighted_price = (
            (self.current_position.get("entry_price", fill_price) * existing_qty)
            + (fill_price * quantity)
        ) / total_qty
        self.current_position["entry_price"] = weighted_price
        self.current_position["quantity"] = total_qty

    def _record_trade_result(self, pnl: float):
        """Update cumulative metrics after trade closes."""
        self.last_portfolio_value = max(0.0, self.last_portfolio_value + pnl)
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        now = datetime.utcnow()
        self._ensure_daily_baseline(now, self.last_portfolio_value)
        self._recalculate_daily_loss(self.last_portfolio_value)
        self._recalculate_drawdown(self.last_portfolio_value)
        self.context_manager.update_context({
            "portfolio": {
                "value": self.last_portfolio_value,
                "balance": self.last_portfolio_value
            }
        })
        self._sync_risk_metrics_context()
    
    async def _handle_position_closed(self, event: PositionClosedEvent):
        """Handle position closed event and update portfolio with PnL.
        
        This ensures portfolio value is updated when positions are closed,
        whether through stop loss, take profit, or signal reversal.
        
        Args:
            event: Position closed event
        """
        try:
            payload = event.payload
            pnl = float(payload.get("pnl", 0.0))
            
            # Update portfolio with realized PnL
            self._record_trade_result(pnl)
            
            # Clear current position tracking
            self.current_position = None
            self.pending_order = None
            
            logger.info(
                "risk_manager_position_closed_processed",
                position_id=payload.get("position_id"),
                symbol=payload.get("symbol"),
                pnl=pnl,
                exit_reason=payload.get("exit_reason"),
                new_portfolio_value=self.last_portfolio_value,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "risk_manager_position_closed_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )

    def _refresh_portfolio_metrics(self, timestamp: datetime, portfolio_value: float):
        """Refresh baseline metrics using the latest portfolio value."""
        effective_timestamp = timestamp or datetime.utcnow()
        self.last_portfolio_value = portfolio_value
        self._ensure_daily_baseline(effective_timestamp, portfolio_value)
        self._recalculate_daily_loss(portfolio_value)
        self._recalculate_drawdown(portfolio_value)
        self._sync_risk_metrics_context()

    def _ensure_daily_baseline(self, timestamp: datetime, portfolio_value: float):
        """Reset daily baseline when a new UTC day starts."""
        current_date = timestamp.date() if isinstance(timestamp, datetime) else datetime.utcnow().date()
        if self.daily_start_date != current_date or self.daily_start_value is None:
            self.daily_start_date = current_date
            self.daily_start_value = portfolio_value
            self.daily_loss_pct = 0.0

    def _recalculate_daily_loss(self, portfolio_value: float):
        """Recompute daily loss percentage."""
        if self.daily_start_value and self.daily_start_value > 0:
            drop = max(0.0, self.daily_start_value - portfolio_value)
            self.daily_loss_pct = drop / self.daily_start_value
        else:
            self.daily_loss_pct = 0.0

    def _recalculate_drawdown(self, portfolio_value: float):
        """Recompute drawdown from recent peak."""
        if self.peak_portfolio_value is None or portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = portfolio_value
        if self.peak_portfolio_value and self.peak_portfolio_value > 0:
            drop = max(0.0, self.peak_portfolio_value - portfolio_value)
            self.current_drawdown = drop / self.peak_portfolio_value
        else:
            self.current_drawdown = 0.0

    def _cooldown_active(self) -> bool:
        """Check if trade cooldown is active."""
        if not self.last_trade_timestamp or self.min_time_between_trades <= 0:
            return False
        elapsed = (datetime.utcnow() - self.last_trade_timestamp).total_seconds()
        return elapsed < self.min_time_between_trades

    def _cooldown_seconds_remaining(self) -> float:
        """Seconds remaining before cooldown expires."""
        if not self.last_trade_timestamp:
            return 0.0
        elapsed = (datetime.utcnow() - self.last_trade_timestamp).total_seconds()
        remaining = self.min_time_between_trades - elapsed
        return max(0.0, remaining)

    def _sync_risk_metrics_context(self):
        """Push latest risk metrics into shared context."""
        self.context_manager.update_context({
            "risk_metrics": {
                "daily_loss_pct": self.daily_loss_pct,
                "max_drawdown_current": self.current_drawdown,
                "consecutive_losses": self.consecutive_losses,
                "last_trade_timestamp": (
                    self.last_trade_timestamp.isoformat() if self.last_trade_timestamp else None
                ),
            }
        })
    
    def assess_risk(
        self,
        signal_strength: float,
        portfolio_value: float,
        available_balance: float,
        current_positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Assess risk for trade.
        
        Args:
            signal_strength: Signal strength (position size as fraction of portfolio)
            portfolio_value: Total portfolio value
            available_balance: Available balance for trading
            current_positions: List of current positions
            
        Returns:
            Dictionary with risk assessment results
        """
        # RISK CHECK: Log risk assessment entry with context
        logger.info(
            "RISK CHECK: position_size=%s portfolio_value=%s",
            signal_strength, portfolio_value
        )
        
        # RISK CHECK: Validate position_size > 0
        if signal_strength <= 0:
            logger.warning("RISK CHECK: position_size <=0 — blocking trade")
            return {
                "can_trade": False,
                "portfolio_heat": 0.0,
                "max_portfolio_heat": self.max_portfolio_heat,
                "available_balance": available_balance
            }
        
        # Calculate portfolio heat
        # Position exposure = quantity * entry_price (cost basis)
        total_exposure = 0.0
        for pos in current_positions:
            if pos:  # Skip None positions
                quantity = float(pos.get("quantity", 0.0) or 0.0)
                entry_price = float(pos.get("entry_price", 0.0) or 0.0)
                position_value = quantity * entry_price
                total_exposure += position_value
        
        portfolio_heat = total_exposure / portfolio_value if portfolio_value > 0 else 0.0
        
        # RISK CHECK: Log heat calculation
        logger.info(
            "RISK CHECK: position_size=%s portfolio_value=%s heat=%s",
            signal_strength, portfolio_value, portfolio_heat
        )
        
        # Check limits
        can_trade = (
            portfolio_heat < self.max_portfolio_heat and
            available_balance > 0
        )
        
        return {
            "can_trade": can_trade,
            "portfolio_heat": portfolio_heat,
            "max_portfolio_heat": self.max_portfolio_heat,
            "available_balance": available_balance
        }
    
    def calculate_position_size(
        self,
        signal: str,
        confidence: float,
        symbol: str,
        price: float,
        portfolio_value: Optional[float] = None
    ) -> float:
        """Calculate position size based on signal strength and confidence.
        
        Args:
            signal: Trading signal (BUY, SELL, STRONG_BUY, etc.)
            confidence: Signal confidence (0.0 to 1.0)
            symbol: Trading symbol
            price: Current price
            portfolio_value: Portfolio value (optional, uses context if not provided)
            
        Returns:
            Position size as fraction of portfolio (0.0 to max_position_size)
        """
        # Get portfolio value from context if not provided
        if portfolio_value is None:
            context = self.context_manager.get_current_context()
            portfolio_value = context.portfolio_value or settings.initial_balance
        
        if portfolio_value <= 0:
            logger.warning(
                "risk_manager_invalid_portfolio_for_position_size",
                portfolio_value=portfolio_value,
                message="Portfolio value is invalid, returning 0 position size"
            )
            return 0.0
        
        # Base position size from signal strength
        if signal in ["STRONG_BUY", "STRONG_SELL"]:
            base_size = self.max_position_size * 0.8  # Use 80% of max for strong signals
        elif signal in ["BUY", "SELL"]:
            base_size = self.max_position_size * 0.5  # Use 50% of max for normal signals
        else:
            base_size = self.max_position_size * 0.3  # Use 30% for other signals
        
        # Scale by confidence
        confidence_multiplier = min(1.0, max(0.0, confidence / 100.0)) if confidence > 1.0 else confidence
        position_size = base_size * confidence_multiplier
        
        # Ensure position size doesn't exceed max
        position_size = min(position_size, self.max_position_size)
        
        # Ensure we have enough balance
        context = self.context_manager.get_current_context()
        available_balance = context.available_balance or portfolio_value
        max_affordable_size = available_balance / portfolio_value if portfolio_value > 0 else 0.0
        position_size = min(position_size, max_affordable_size)
        
        logger.debug(
            "risk_manager_position_size_calculated",
            signal=signal,
            confidence=confidence,
            base_size=base_size,
            confidence_multiplier=confidence_multiplier,
            calculated_size=position_size,
            max_position_size=self.max_position_size,
            available_balance=available_balance
        )
        
        return position_size
    
    def check_risk_limits(
        self,
        position_size: float,
        current_exposure: Optional[float] = None,
        max_position_size: Optional[float] = None,
        max_loss: Optional[float] = None
    ) -> Dict[str, Any]:
        """Check if proposed trade violates risk limits.
        
        Args:
            position_size: Proposed position size (fraction of portfolio)
            current_exposure: Current portfolio exposure (optional)
            max_position_size: Maximum position size (optional, uses instance default)
            max_loss: Maximum loss limit (optional)
            
        Returns:
            Dictionary with limit check results
        """
        max_pos_size = max_position_size or self.max_position_size
        context = self.context_manager.get_current_context()
        portfolio_value = context.portfolio_value or settings.initial_balance
        
        # Check position size limit
        position_size_ok = position_size <= max_pos_size
        
        # Check portfolio heat
        if current_exposure is None:
            # Calculate from context
            current_positions = [context.position] if context.position else []
            total_exposure = 0.0
            for pos in current_positions:
                if pos:
                    quantity = float(pos.get("quantity", 0.0) or 0.0)
                    entry_price = float(pos.get("entry_price", 0.0) or 0.0)
                    total_exposure += quantity * entry_price
            current_exposure = total_exposure
        
        portfolio_heat = current_exposure / portfolio_value if portfolio_value > 0 else 0.0
        portfolio_heat_ok = portfolio_heat < self.max_portfolio_heat
        
        # Check daily loss limit
        daily_loss_ok = self.daily_loss_pct < self.max_daily_loss if self.max_daily_loss else True
        
        # Check drawdown limit
        drawdown_ok = self.current_drawdown < self.max_drawdown_limit if self.max_drawdown_limit else True
        
        # Check consecutive losses
        consecutive_losses_ok = (
            self.consecutive_losses < self.max_consecutive_losses_limit
            if self.max_consecutive_losses_limit
            else True
        )
        
        all_limits_ok = (
            position_size_ok and
            portfolio_heat_ok and
            daily_loss_ok and
            drawdown_ok and
            consecutive_losses_ok
        )
        
        return {
            "limits_ok": all_limits_ok,
            "position_size_ok": position_size_ok,
            "portfolio_heat_ok": portfolio_heat_ok,
            "daily_loss_ok": daily_loss_ok,
            "drawdown_ok": drawdown_ok,
            "consecutive_losses_ok": consecutive_losses_ok,
            "position_size": position_size,
            "max_position_size": max_pos_size,
            "portfolio_heat": portfolio_heat,
            "max_portfolio_heat": self.max_portfolio_heat,
            "daily_loss_pct": self.daily_loss_pct,
            "max_daily_loss": self.max_daily_loss,
            "current_drawdown": self.current_drawdown,
            "max_drawdown": self.max_drawdown_limit,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses_limit
        }
    
    def calculate_portfolio_risk(self) -> Dict[str, Any]:
        """Calculate portfolio-level risk metrics.
        
        Returns:
            Dictionary with portfolio risk metrics
        """
        context = self.context_manager.get_current_context()
        portfolio_value = context.portfolio_value or settings.initial_balance
        available_balance = context.available_balance or portfolio_value
        
        # Calculate current exposure
        current_positions = [context.position] if context.position else []
        total_exposure = 0.0
        for pos in current_positions:
            if pos:
                quantity = float(pos.get("quantity", 0.0) or 0.0)
                entry_price = float(pos.get("entry_price", 0.0) or 0.0)
                total_exposure += quantity * entry_price
        
        portfolio_heat = total_exposure / portfolio_value if portfolio_value > 0 else 0.0
        
        return {
            "portfolio_value": portfolio_value,
            "available_balance": available_balance,
            "total_exposure": total_exposure,
            "portfolio_heat": portfolio_heat,
            "max_portfolio_heat": self.max_portfolio_heat,
            "daily_loss_pct": self.daily_loss_pct,
            "max_daily_loss": self.max_daily_loss,
            "current_drawdown": self.current_drawdown,
            "max_drawdown": self.max_drawdown_limit,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses_limit,
            "risk_score": 1.0 - min(1.0, portfolio_heat / self.max_portfolio_heat) if self.max_portfolio_heat > 0 else 1.0
        }
    
    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """Calculate stop loss price."""
        if side == "BUY":
            return entry_price * (1 - self.stop_loss_pct)
        else:
            return entry_price * (1 + self.stop_loss_pct)
    
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Calculate take profit price."""
        if side == "BUY":
            return entry_price * (1 + self.take_profit_pct)
        else:
            return entry_price * (1 - self.take_profit_pct)
    
    async def _check_exit_conditions(
        self,
        symbol: str,
        current_price: float,
        position: Dict[str, Any]
    ) -> Optional[str]:
        """Check if exit conditions (stop loss or take profit) are met.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            position: Position dictionary from context
            
        Returns:
            Exit reason if condition met, None otherwise
        """
        if not position:
            return None
        
        entry_price = float(position.get("entry_price", 0.0))
        side = position.get("side")
        stop_loss = position.get("stop_loss")
        take_profit = position.get("take_profit")
        
        if not entry_price or not side:
            return None
        
        # Calculate stop loss and take profit if not stored
        if not stop_loss:
            stop_loss = self.calculate_stop_loss(entry_price, side)
        if not take_profit:
            take_profit = self.calculate_take_profit(entry_price, side)
        
        # Check stop loss
        if side == "BUY":
            # For long position: exit if price drops to or below stop loss
            if current_price <= stop_loss:
                logger.warning(
                    "stop_loss_triggered",
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    stop_loss=stop_loss,
                    side=side
                )
                return "stop_loss"
            # For long position: exit if price rises to or above take profit
            if current_price >= take_profit:
                logger.info(
                    "take_profit_triggered",
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    take_profit=take_profit,
                    side=side
                )
                return "take_profit"
        else:  # SELL (short position)
            # For short position: exit if price rises to or above stop loss
            if current_price >= stop_loss:
                logger.warning(
                    "stop_loss_triggered",
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    stop_loss=stop_loss,
                    side=side
                )
                return "stop_loss"
            # For short position: exit if price drops to or below take profit
            if current_price <= take_profit:
                logger.info(
                    "take_profit_triggered",
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    take_profit=take_profit,
                    side=side
                )
                return "take_profit"
        
        return None
    
    async def _emit_exit_decision(
        self,
        symbol: str,
        exit_reason: str,
        current_price: float
    ):
        """Emit exit decision event when exit condition is met.
        
        Args:
            symbol: Trading symbol
            exit_reason: Reason for exit (stop_loss, take_profit)
            current_price: Current market price
        """
        try:
            context = self.context_manager.get_current_context()
            position = context.position
            if not position:
                return
            
            # Determine exit signal based on position side
            position_side = position.get("side")
            if position_side == "BUY":
                exit_signal = "SELL"  # Close long position
            else:
                exit_signal = "BUY"  # Close short position
            
            # Create exit decision event
            exit_decision = DecisionReadyEvent(
                source="risk_manager",
                payload={
                    "symbol": symbol,
                    "signal": exit_signal,
                    "confidence": 1.0,  # High confidence for stop loss/take profit exits
                    "position_size": 0.0,  # Full position exit
                    "exit_reason": exit_reason,
                    "current_price": current_price,
                    "reasoning_chain": {
                        "exit_reason": exit_reason,
                        "triggered_at_price": current_price,
                        "position_side": position_side,
                        "entry_price": position.get("entry_price")
                    },
                    "timestamp": datetime.utcnow()
                }
            )
            
            await event_bus.publish(exit_decision)
            
            logger.info(
                "exit_decision_emitted",
                symbol=symbol,
                exit_reason=exit_reason,
                exit_signal=exit_signal,
                current_price=current_price,
                event_id=exit_decision.event_id
            )
            
        except Exception as e:
            logger.error(
                "exit_decision_emit_failed",
                symbol=symbol,
                exit_reason=exit_reason,
                error=str(e),
                exc_info=True
            )

