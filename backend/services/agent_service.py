"""
Agent service for communicating with the AI agent core.

Provides methods for interacting with the agent service via Redis queues.
"""

from typing import Optional, Dict, Any, List
import json
import uuid
import asyncio
import time

from backend.core.redis import enqueue_command, get_response, cache_response
from backend.core.config import settings


class AgentService:
    """Service for communicating with agent."""
    
    def __init__(self):
        """Initialize agent service."""
        self.command_queue = settings.agent_command_queue
        self.response_queue = settings.agent_response_queue
    
    async def _send_command(
        self,
        command: str,
        parameters: Dict[str, Any] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Send command to agent and wait for response."""
        
        request_id = str(uuid.uuid4())
        
        # Create command message
        message = {
            "request_id": request_id,
            "command": command,
            "parameters": parameters or {},
            "timestamp": time.time()
        }
        
        # Send command
        success = await enqueue_command(message, self.command_queue)
        if not success:
            return None
        
        # Wait for response (check cache first)
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = await get_response(request_id, timeout=1)
            if response:
                return response
            
            await asyncio.sleep(0.5)
        
        return None
    
    async def get_prediction(
        self,
        symbol: str = "BTCUSD",
        context: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Get prediction from agent."""
        
        response = await self._send_command(
            "predict",
            parameters={
                "symbol": symbol,
                "context": context or {}
            },
            timeout=60  # Predictions may take longer
        )
        
        return response
    
    async def execute_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Execute trade via agent."""
        
        response = await self._send_command(
            "execute_trade",
            parameters={
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit
            },
            timeout=30
        )
        
        return response
    
    async def get_agent_status(self) -> Optional[Dict[str, Any]]:
        """Get agent status."""
        
        response = await self._send_command(
            "get_status",
            parameters={},
            timeout=5
        )
        
        # Return default status if agent is not responding
        if not response:
            return {
                "available": False,
                "state": "UNKNOWN",
                "message": "Agent service unavailable"
            }
        
        return response
    
    async def control_agent(
        self,
        action: str,
        parameters: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Control agent (start, stop, pause, resume, restart)."""
        
        response = await self._send_command(
            "control",
            parameters={
                "action": action,
                "parameters": parameters or {}
            },
            timeout=10
        )
        
        return response


# Global agent service instance
agent_service = AgentService()

