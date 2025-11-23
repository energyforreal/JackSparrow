"""
Reasoning event handler.

Handles reasoning events and updates context.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    ReasoningCompleteEvent,
    DecisionReadyEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class ReasoningEventHandler:
    """Handler for reasoning events."""
    
    def __init__(self):
        """Initialize reasoning event handler."""
        self.context_manager = context_manager
    
    async def handle_reasoning_complete(self, event: ReasoningCompleteEvent):
        """Handle reasoning complete event.
        
        Args:
            event: Reasoning complete event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            reasoning_chain = payload.get("reasoning_chain", {})
            final_confidence = payload.get("final_confidence", 0.0)
            
            # Update context with reasoning chain
            self.context_manager.update_context({
                "decision": {
                    "reasoning_chain": reasoning_chain,
                    "confidence": final_confidence,
                    "symbol": symbol
                }
            })
            
            logger.info(
                "reasoning_complete_handled",
                symbol=symbol,
                chain_id=reasoning_chain.get("chain_id"),
                final_confidence=final_confidence,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "reasoning_complete_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def handle_decision_ready(self, event: DecisionReadyEvent):
        """Handle decision ready event.
        
        Args:
            event: Decision ready event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            signal = payload.get("signal")
            confidence = payload.get("confidence", 0.0)
            position_size = payload.get("position_size", 0.0)
            
            # Update context with decision
            self.context_manager.update_context({
                "decision": {
                    "signal": signal,
                    "confidence": confidence,
                    "position_size": position_size,
                    "symbol": symbol
                }
            })
            
            logger.info(
                "decision_ready_handled",
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                position_size=position_size,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "decision_ready_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(EventType.REASONING_COMPLETE, self.handle_reasoning_complete)
        event_bus.subscribe(EventType.DECISION_READY, self.handle_decision_ready)
        
        logger.info("reasoning_handlers_registered")


# Global handler instance
reasoning_handler = ReasoningEventHandler()

