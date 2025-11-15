"""
Intelligent Agent main entry point.

Orchestrates all agent components and provides main agent loop.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agent.core.config import settings
from agent.core.state_machine import AgentState, AgentStateMachine
from agent.core.context_manager import ContextManager, context_manager
from agent.core.mcp_orchestrator import MCPOrchestrator, mcp_orchestrator
from agent.core.learning_system import LearningSystem
from agent.core.redis import get_redis
from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.risk.risk_manager import RiskManager
from agent.data.delta_client import DeltaExchangeClient


class IntelligentAgent:
    """Main intelligent agent class."""
    
    def __init__(self):
        """Initialize intelligent agent."""
        self.state_machine = AgentStateMachine()
        self.context_manager = context_manager
        self.mcp_orchestrator = mcp_orchestrator
        self.learning_system = LearningSystem()
        self.risk_manager = RiskManager()
        self.delta_client = DeltaExchangeClient()
        self.model_registry = MCPModelRegistry()
        self.model_discovery = ModelDiscovery(self.model_registry)
        self.running = False
        self.command_queue = settings.agent_command_queue
        self.response_queue = settings.agent_response_queue
    
    async def initialize(self):
        """Initialize agent."""
        print("Initializing agent...")
        
        # Initialize MCP orchestrator
        await self.mcp_orchestrator.initialize()
        
        # Discover and register models
        print("Discovering models...")
        discovered = await self.model_discovery.discover_models()
        print(f"Discovered {len(discovered)} models: {discovered}")
        
        # Initialize state machine
        self.state_machine.current_state = AgentState.INITIALIZING
        self.context_manager.update_context({"state": AgentState.INITIALIZING})
        
        print("Agent initialized successfully")
        
        # Transition to OBSERVING
        self.state_machine.transition_to(
            AgentState.OBSERVING,
            {"initialized": True, "manual_transition": True}
        )
        self.context_manager.update_context({"state": AgentState.OBSERVING})
    
    async def shutdown(self):
        """Shutdown agent."""
        print("Shutting down agent...")
        self.running = False
        await self.mcp_orchestrator.shutdown()
        print("Agent shut down")
    
    async def start(self):
        """Start agent main loop."""
        self.running = True
        
        # Start command handler
        command_task = asyncio.create_task(self._command_handler())
        
        # Start main loop
        main_task = asyncio.create_task(self._main_loop())
        
        try:
            await asyncio.gather(command_task, main_task)
        except asyncio.CancelledError:
            pass
    
    async def _command_handler(self):
        """Handle commands from Redis queue."""
        redis = await get_redis()
        
        while self.running:
            try:
                # Check for commands
                result = await redis.brpop(self.command_queue, timeout=1)
                if result:
                    _, message = result
                    command = json.loads(message)
                    await self._process_command(command)
            except Exception as e:
                print(f"Error in command handler: {e}")
                await asyncio.sleep(1)
    
    async def _process_command(self, command: Dict[str, Any]):
        """Process command from backend."""
        request_id = command.get("request_id")
        cmd = command.get("command")
        params = command.get("parameters", {})
        
        try:
            if cmd == "predict":
                response = await self._handle_predict(params)
            elif cmd == "execute_trade":
                response = await self._handle_execute_trade(params)
            elif cmd == "get_status":
                response = await self._handle_get_status()
            elif cmd == "control":
                response = await self._handle_control(params)
            else:
                response = {"success": False, "error": f"Unknown command: {cmd}"}
            
            # Send response
            response["request_id"] = request_id
            redis = await get_redis()
            await redis.lpush(f"response:{request_id}", json.dumps(response))
            
        except Exception as e:
            error_response = {
                "request_id": request_id,
                "success": False,
                "error": str(e)
            }
            redis = await get_redis()
            await redis.lpush(f"response:{request_id}", json.dumps(error_response))
    
    async def _handle_predict(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle prediction request."""
        symbol = params.get("symbol", settings.agent_symbol)
        context = params.get("context", {})
        
        decision = await self.mcp_orchestrator.get_trading_decision(
            symbol=symbol,
            market_context=context
        )
        
        return {"success": True, "data": decision}
    
    async def _handle_execute_trade(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle trade execution request."""
        # Placeholder - would execute trade via Delta Exchange
        return {
            "success": True,
            "data": {
                "trade_id": f"trade_{datetime.utcnow().timestamp()}",
                "status": "EXECUTED",
                "symbol": params.get("symbol"),
                "side": params.get("side"),
                "quantity": params.get("quantity"),
                "price": params.get("price", 50000.0)
            }
        }
    
    async def _handle_get_status(self) -> Dict[str, Any]:
        """Handle status request."""
        health = await self.mcp_orchestrator.get_health_status()
        
        return {
            "success": True,
            "data": {
                "available": True,
                "state": self.state_machine.current_state.value,
                "health": health,
                "latency_ms": 5.0
            }
        }
    
    async def _handle_control(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle control command."""
        action = params.get("action")
        
        # Handle actions
        if action == "start":
            self.state_machine.transition_to(
                AgentState.OBSERVING,
                {"manual_transition": True}
            )
        elif action == "stop":
            self.running = False
        
        return {
            "success": True,
            "data": {
                "state": self.state_machine.current_state.value,
                "message": f"Agent {action} completed"
            }
        }
    
    async def _main_loop(self):
        """Main agent loop."""
        while self.running:
            try:
                # Main loop logic would go here
                # For now, just sleep
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(1)


async def main():
    """Main entry point."""
    agent = IntelligentAgent()
    
    try:
        await agent.initialize()
        await agent.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await agent.shutdown()
    except Exception as e:
        print(f"Error: {e}")
        await agent.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

