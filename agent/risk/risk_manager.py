"""Risk management service."""

from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime
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
        self.context_manager = context_manager
        self._monitoring = False
    
    async def initialize(self):
        """Initialize risk manager and register event handlers."""
        event_bus.subscribe(EventType.DECISION_READY, self._handle_decision_ready)
        event_bus.subscribe(EventType.MARKET_TICK, self._handle_market_tick)
        event_bus.subscribe(EventType.ORDER_FILL, self._handle_order_fill)
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
            
            # Skip HOLD signals
            if signal == "HOLD":
                return
            
            # Get context
            context = self.context_manager.get_current_context()
            portfolio_value = context.portfolio_value
            available_balance = context.available_balance
            current_positions = [context.position] if context.position else []
            
            # Assess risk
            risk_assessment = self.assess_risk(
                signal_strength=abs(position_size),
                portfolio_value=portfolio_value,
                available_balance=available_balance,
                current_positions=current_positions
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
            
            # Approve trade
            await self._emit_risk_approved(
                symbol=symbol,
                side="BUY" if signal in ["BUY", "STRONG_BUY"] else "SELL",
                quantity=position_size * portfolio_value,
                price=context.current_price or 0.0,
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
            # Check portfolio heat continuously
            context = self.context_manager.get_current_context()
            if context.position:
                # Monitor position for stop loss / take profit
                # This would be handled by execution module
                pass
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
            # Update risk metrics after order fill
            context = self.context_manager.get_current_context()
            # Risk manager tracks positions for heat calculation
        except Exception as e:
            logger.error(
                "risk_manager_order_fill_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
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
            
            await event_bus.publish(event)
            
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
    
    def assess_risk(
        self,
        signal_strength: float,
        portfolio_value: float,
        available_balance: float,
        current_positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Assess risk for trade."""
        
        # Calculate portfolio heat
        total_exposure = sum(pos.get("value", 0) for pos in current_positions)
        portfolio_heat = total_exposure / portfolio_value if portfolio_value > 0 else 0.0
        
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

