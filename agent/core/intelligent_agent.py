"""
Intelligent Agent main entry point.

Orchestrates all agent components and provides main agent loop.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import json
import structlog

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def _configure_utf8_stdio() -> None:
    """Ensure Windows consoles use UTF-8 to avoid encoding crashes."""
    if os.name != "nt":
        return
    
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


_configure_utf8_stdio()

from agent.core.config import settings

logger = structlog.get_logger()
from agent.core.state_machine import AgentState, AgentStateMachine
from agent.core.context_manager import ContextManager, context_manager
from agent.core.mcp_orchestrator import MCPOrchestrator, mcp_orchestrator
from agent.core.learning_system import LearningSystem
from agent.core.execution import execution_module
from agent.core.redis import get_redis
from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.risk.risk_manager import RiskManager
from agent.data.delta_client import DeltaExchangeClient
from agent.data.market_data_service import MarketDataService
from agent.events.event_bus import event_bus
from agent.events.schemas import AgentCommandEvent, EventType
from agent.events.handlers import (
    market_data_handler,
    feature_handler,
    model_handler,
    reasoning_handler
)


class IntelligentAgent:
    """Main intelligent agent class."""
    
    def __init__(self):
        """Initialize intelligent agent."""
        self.state_machine = AgentStateMachine(context_manager=context_manager)
        self.context_manager = context_manager
        self.mcp_orchestrator = mcp_orchestrator
        self.model_registry = MCPModelRegistry()
        self.learning_system = LearningSystem(model_registry=self.model_registry)
        self.risk_manager = RiskManager()
        self.delta_client = DeltaExchangeClient()
        self.model_discovery = ModelDiscovery(self.model_registry)
        self.market_data_service = MarketDataService()
        self.running = False
        self.command_queue = settings.agent_command_queue
        # Response mechanism uses Redis key-value store (response:{request_id})
        # Legacy list-based response queue removed - backend uses get_response() which reads from key-value
    
    async def initialize(self):
        """Initialize agent."""
        logger.info("agent_initializing", service="agent")
        
        # Initialize event bus
        await event_bus.initialize()
        
        # Initialize MCP orchestrator
        await self.mcp_orchestrator.initialize()
        
        # Initialize model registry (registers event handlers)
        await self.model_registry.initialize()
        
        # Discover and register models
        logger.info("agent_discovering_models", service="agent")
        try:
            discovered = await self.model_discovery.discover_models()
            logger.info(
                "agent_models_discovered",
                service="agent",
                count=len(discovered),
                models=discovered
            )
            if not discovered:
                logger.warning(
                    "agent_no_models_discovered",
                    service="agent",
                    message="No models were discovered. Agent will continue but predictions may fail."
                )
        except Exception as e:
            logger.error(
                "agent_model_discovery_failed",
                service="agent",
                error=str(e),
                exc_info=True,
                message="Model discovery failed, but agent will continue. Some features may be unavailable."
            )
        
        # Initialize all components with event handlers
        await self.state_machine.initialize()
        await self.risk_manager.initialize()
        await execution_module.initialize()
        await self.learning_system.initialize()
        await self.market_data_service.initialize()
        
        # Initialize model weights from performance metrics if available
        try:
            if self.model_registry.models:
                model_names = list(self.model_registry.models.keys())
                performance_weights = self.learning_system.get_updated_weights(model_names)
                if performance_weights:
                    self.model_registry.update_weights_from_performance(performance_weights)
                    logger.info(
                        "agent_model_weights_initialized",
                        service="agent",
                        weights=performance_weights
                    )
        except Exception as e:
            logger.warning(
                "agent_model_weights_init_failed",
                service="agent",
                error=str(e),
                message="Model weights will use default equal weights"
            )
        
        # Register event handlers
        await market_data_handler.register_handlers()
        await feature_handler.register_handlers()
        await model_handler.register_handlers()
        await reasoning_handler.register_handlers()
        
        # Initialize state machine
        self.state_machine.current_state = AgentState.INITIALIZING
        self.context_manager.update_context({"state": AgentState.INITIALIZING})
        
        logger.info("agent_initialized_successfully", service="agent")
        
        # Transition to OBSERVING
        await self.state_machine._transition_to(
            AgentState.OBSERVING,
            "Initialization complete"
        )
        
        # Start market data streaming (non-blocking, allow agent to start even if this fails)
        try:
            await self.market_data_service.start_market_data_stream(
                symbols=[settings.agent_symbol],
                interval=settings.agent_interval
            )
            logger.info(
                "agent_market_data_stream_started",
                service="agent",
                symbols=[settings.agent_symbol],
                interval=settings.agent_interval
            )
        except Exception as e:
            # Log error but don't crash - agent can still operate without market data streaming
            logger.warning(
                "agent_market_data_stream_start_failed",
                service="agent",
                error=str(e),
                error_type=type(e).__name__,
                message="Agent will continue without market data streaming. Some features may be unavailable.",
                exc_info=True
            )
    
    async def shutdown(self):
        """Shutdown agent."""
        logger.info("agent_shutting_down", service="agent")
        self.running = False
        
        # Shutdown all components
        await self.market_data_service.shutdown()
        await self.learning_system.shutdown()
        await execution_module.shutdown()
        await self.risk_manager.shutdown()
        await self.model_registry.shutdown()
        await self.mcp_orchestrator.shutdown()
        await event_bus.shutdown()
        
        logger.info("agent_shut_down", service="agent")
    
    async def start(self):
        """Start agent main loop."""
        self.running = True
        
        # Start command handler (for backward compatibility)
        command_task = asyncio.create_task(self._command_handler())
        
        # Start event bus consumption (replaces polling loop)
        event_task = asyncio.create_task(event_bus.start_consuming())
        
        try:
            await asyncio.gather(command_task, event_task)
        except asyncio.CancelledError:
            pass
    
    async def _command_handler(self):
        """Handle commands from Redis queue with reconnection logic."""
        logger.info(
            "agent_command_handler_started",
            service="agent",
            command_queue=self.command_queue,
            message="Command handler is now listening for commands from backend"
        )
        reconnect_attempts = 0
        max_reconnect_delay = 60  # Maximum delay in seconds
        base_reconnect_delay = 1  # Base delay in seconds
        
        while self.running:
            try:
                # Get Redis connection with health check
                redis = await get_redis()
                if redis is None:
                    logger.warning(
                        "agent_redis_unavailable",
                        message="Command handler paused - Redis unavailable",
                        reconnect_attempt=reconnect_attempts
                    )
                    # Exponential backoff for reconnection
                    delay = min(
                        base_reconnect_delay * (2 ** reconnect_attempts),
                        max_reconnect_delay
                    )
                    reconnect_attempts += 1
                    await asyncio.sleep(delay)
                    continue
                
                # Reset reconnect attempts on successful connection
                if reconnect_attempts > 0:
                    logger.info(
                        "agent_redis_reconnected",
                        message="Command handler resumed - Redis available",
                        service="agent"
                    )
                    reconnect_attempts = 0
                
                # Check for commands with timeout
                try:
                    result = await redis.brpop(self.command_queue, timeout=1)
                    if result:
                        _, message = result
                        command = json.loads(message)
                        await self._process_command(command)
                except (ConnectionError, TimeoutError, OSError) as redis_error:
                    # Redis connection error during operation
                    logger.warning(
                        "agent_redis_operation_failed",
                        service="agent",
                        error=str(redis_error),
                        error_type=type(redis_error).__name__,
                        reconnect_attempt=reconnect_attempts
                    )
                    # Invalidate Redis connection to force reconnection
                    from agent.core.redis import _redis_client
                    if _redis_client is not None:
                        try:
                            await _redis_client.close()
                        except Exception:
                            pass
                    from agent.core.redis import _redis_client
                    import agent.core.redis as redis_module
                    redis_module._redis_client = None
                    
                    # Exponential backoff
                    delay = min(
                        base_reconnect_delay * (2 ** reconnect_attempts),
                        max_reconnect_delay
                    )
                    reconnect_attempts += 1
                    await asyncio.sleep(delay)
                    continue
                    
            except Exception as e:
                logger.error(
                    "agent_command_handler_error",
                    service="agent",
                    error=str(e),
                    error_type=type(e).__name__,
                    reconnect_attempt=reconnect_attempts,
                    exc_info=True
                )
                # Exponential backoff for unexpected errors
                delay = min(
                    base_reconnect_delay * (2 ** reconnect_attempts),
                    max_reconnect_delay
                )
                reconnect_attempts += 1
                await asyncio.sleep(delay)
    
    async def _process_command(self, command: Dict[str, Any]):
        """Process command from backend."""
        request_id = command.get("request_id")
        cmd = command.get("command")
        params = command.get("parameters", {})
        
        try:
            # Validate command before processing
            if not cmd:
                logger.warning(
                    "agent_command_invalid",
                    request_id=request_id,
                    reason="Missing command field"
                )
                await self._send_response(request_id, {
                    "success": False,
                    "error": "Missing command field"
                })
                return
            
            # Emit command as event for event-driven processing
            try:
                command_event = AgentCommandEvent(
                    source="intelligent_agent",
                    payload={
                        "command": cmd,
                        "parameters": params or {},
                        "request_id": request_id or str(uuid.uuid4())
                    }
                )
                await event_bus.publish(command_event)
            except Exception as e:
                logger.warning(
                    "agent_command_event_publish_failed",
                    request_id=request_id,
                    command=cmd,
                    error=str(e),
                    exc_info=True,
                    message="Continuing with command handling despite event publish failure"
                )
            
            # Handle command (backward compatibility)
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
            
            await self._send_response(request_id, response)
            
        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e)
            }
            await self._send_response(request_id, error_response)
    
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
        
        # Extract detailed health information
        feature_server_health = health.get("feature_server", {})
        model_registry_health = health.get("model_registry", {})
        reasoning_engine_health = health.get("reasoning_engine", {})
        
        # Extract delta_exchange status from feature_server (which includes market_data_service)
        delta_exchange_status = {}
        if feature_server_health:
            market_data_service = feature_server_health.get("market_data_service", {})
            if market_data_service:
                delta_status = market_data_service.get("status", "unknown")
                circuit_breaker = market_data_service.get("circuit_breaker", {})
                delta_exchange_status = {
                    "status": delta_status,
                    "latency_ms": None,  # Market data service doesn't track latency separately
                    "circuit_breaker": circuit_breaker
                }
            else:
                delta_exchange_status = {
                    "status": "unknown",
                    "latency_ms": None
                }
        else:
            delta_exchange_status = {
                "status": "unknown",
                "latency_ms": None
            }
        
        # Extract model_nodes status from model_registry
        model_nodes_status = {}
        if model_registry_health:
            total_models = model_registry_health.get("total_models", 0)
            healthy_models = model_registry_health.get("healthy_models", 0)
            registry_health = model_registry_health.get("registry_health", "unknown")
            
            # Determine status based on model registry health
            if total_models == 0:
                model_status = "unknown"  # No models loaded, but not an error
            elif healthy_models == 0:
                model_status = "down"
            elif healthy_models < total_models:
                model_status = "degraded"
            else:
                model_status = "up"
            
            model_nodes_status = {
                "status": model_status,
                "healthy_models": healthy_models,
                "total_models": total_models,
                "registry_health": registry_health
            }
        else:
            model_nodes_status = {
                "status": "unknown",
                "healthy_models": 0,
                "total_models": 0
            }
        
        # Build comprehensive health response
        detailed_health = {
            "feature_server": {
                "status": feature_server_health.get("status", "unknown"),
                "latency_ms": None,  # Feature server doesn't track latency
                "feature_registry_count": feature_server_health.get("feature_registry_count", 0)
            },
            "model_nodes": model_nodes_status,
            "delta_exchange": delta_exchange_status,
            "reasoning_engine": {
                "status": reasoning_engine_health.get("status", "unknown"),
                "latency_ms": None  # Reasoning engine doesn't track latency
            },
            "overall_status": health.get("overall_status", "unknown")
        }
        
        return {
            "success": True,
            "data": {
                "available": True,
                "state": self.state_machine.current_state.value,
                "health": health,  # Keep original health structure for backward compatibility
                "detailed_health": detailed_health,  # New detailed structure
                "latency_ms": 5.0
            }
        }
    
    async def _handle_control(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle control command."""
        action = params.get("action")
        
        # Handle actions
        if action == "start":
            await self.state_machine._transition_to(
                AgentState.OBSERVING,
                "Manual start command"
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
    
    # Main loop replaced by event bus consumption
    # Events drive all agent behavior now

    async def _send_response(self, request_id: str, payload: Dict[str, Any], ttl: int = 120):
        """Send response back to backend via Redis key-value store.
        
        Backend polls for responses using get_response() which reads from response:{request_id} key.
        TTL ensures responses are automatically cleaned up after expiration.
        """
        response = dict(payload)
        response["request_id"] = request_id
        redis = await get_redis()
        
        if redis is None:
            logger.warning(
                "agent_response_send_failed",
                request_id=request_id,
                message="Redis unavailable - response not sent"
            )
            return
        
        try:
            # Cache response for backend polling using key-value store
            # Backend reads from response:{request_id} key using get_response()
            await redis.setex(f"response:{request_id}", ttl, json.dumps(response))
            logger.debug(
                "agent_response_sent",
                request_id=request_id,
                ttl=ttl,
                service="agent"
            )
        except Exception as e:
            logger.error(
                "agent_response_send_error",
                request_id=request_id,
                error=str(e),
                exc_info=True
            )


async def main():
    """Main entry point."""
    agent = IntelligentAgent()
    
    try:
        await agent.initialize()
        await agent.start()
    except KeyboardInterrupt:
        logger.info("agent_shutdown_requested", service="agent")
        await agent.shutdown()
    except Exception as e:
        logger.error(
            "agent_startup_error",
            service="agent",
            error=str(e),
            exc_info=True
        )
        await agent.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

