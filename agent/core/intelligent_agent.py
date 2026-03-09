"""
Intelligent Agent main entry point.

Orchestrates all agent components and provides main agent loop.
"""

import asyncio
import os
import sys
import time
import uuid
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timezone
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


def _json_serializer(obj: Any) -> Any:
    """Serialize non-JSON-native objects for Redis responses."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)

from agent.core.config import settings
from agent.core.logging_utils import configure_logging

SESSION_ID = configure_logging()
logger = structlog.get_logger()
from agent.core.state_machine import AgentState, AgentStateMachine
from agent.core.context_manager import ContextManager, context_manager
from agent.core.mcp_orchestrator import MCPOrchestrator, mcp_orchestrator
from agent.core.learning_system import LearningSystem
from agent.core.execution import execution_module
from agent.core.redis_config import get_redis
from agent.models.model_discovery import ModelDiscovery
from agent.risk.risk_manager import RiskManager
from agent.data.delta_client import DeltaExchangeClient
from agent.data.market_data_service import MarketDataService
from agent.data.feature_server_api import FeatureServerAPI
from agent.events.event_bus import event_bus
from agent.events.schemas import EventType
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
        self.session_id = SESSION_ID
        self.context_manager = context_manager
        self.mcp_orchestrator = mcp_orchestrator
        self.model_registry = None  # Set after MCP orchestrator initializes
        self.learning_system = LearningSystem()
        self.state_machine = AgentStateMachine(
            context_manager=context_manager,
            learning_system=self.learning_system,
            model_registry=None,
        )
        self.risk_manager = RiskManager(config=settings)
        self.delta_client = DeltaExchangeClient()
        self.model_discovery = None  # Will be initialized after model_registry is set
        self.market_data_service = MarketDataService()
        self.feature_server_api = FeatureServerAPI(
            feature_server=self.mcp_orchestrator.feature_server,
            host=settings.feature_server_host,
            port=settings.feature_server_port,
        )
        self.running = False
        self.command_queue = settings.agent_command_queue
        self.default_symbol = settings.trading_symbol or settings.agent_symbol
        timeframe_list = settings.parsed_timeframes()
        self.timeframes = timeframe_list or [settings.agent_interval]
        self.primary_interval = self.timeframes[0]
        self.trading_mode = settings.trading_mode
        self.initial_balance = settings.initial_balance
        self.confidence_threshold = settings.min_confidence_threshold
        self.start_mode = settings.agent_start_mode
        # Response mechanism uses Redis key-value store (response:{request_id})
        # Legacy list-based response queue removed - backend uses get_response() which reads from key-value
    
    async def initialize(self):
        """Initialize agent."""
        # Seed initial context using environment configuration
        await self.context_manager.update_state({
            "symbol": self.default_symbol,
            "timeframes": self.timeframes,
            "trading_mode": self.trading_mode,
            "confidence_threshold": self.confidence_threshold,
            "portfolio": {
                "value": self.initial_balance,
                "balance": self.initial_balance,
            },
        })

        logger.info(
            "agent_startup",
            service="agent",
            environment=settings.environment,
            agent_mode=self.start_mode,
            symbol=self.default_symbol,
            trading_mode=self.trading_mode,
            timeframes=self.timeframes,
        )
        
        # Log comprehensive configuration for verification
        logger.info(
            "agent_configuration_loaded",
            service="agent",
            # Agent Configuration
            agent_start_mode=settings.agent_start_mode,
            agent_symbol=settings.agent_symbol,
            agent_interval=settings.agent_interval,
            trading_symbol=settings.trading_symbol,
            trading_mode=settings.trading_mode,
            paper_trading_mode=settings.paper_trading_mode,
            # Risk Management
            max_position_size=settings.max_position_size,
            max_portfolio_heat=settings.max_portfolio_heat,
            stop_loss_percentage=settings.stop_loss_percentage,
            take_profit_percentage=settings.take_profit_percentage,
            max_daily_loss=settings.max_daily_loss,
            max_drawdown=settings.max_drawdown,
            max_consecutive_losses=settings.max_consecutive_losses,
            min_time_between_trades=settings.min_time_between_trades,
            min_confidence_threshold=settings.min_confidence_threshold,
            # Trading Session
            initial_balance=settings.initial_balance,
            update_interval=settings.update_interval,
            timeframes=settings.timeframes,
            # Model Configuration
            model_path=settings.model_path,
            model_dir=settings.model_dir,
            model_discovery_enabled=settings.model_discovery_enabled,
            model_auto_register=settings.model_auto_register,
            # Feature Server
            feature_server_host=settings.feature_server_host,
            feature_server_port=settings.feature_server_port,
            message="Agent configuration loaded from environment variables"
        )
        
        # Initialize event bus
        await event_bus.initialize()
        
        # Initialize MCP orchestrator
        await self.mcp_orchestrator.initialize()
        await self.feature_server_api.start()

        # Set model registry after MCP orchestrator is initialized
        # Model discovery and initialization is handled by MCP orchestrator
        self.model_registry = self.mcp_orchestrator.model_registry
        self.state_machine.model_registry = self.model_registry
        self.model_discovery = ModelDiscovery(self.model_registry)
        
        # Initialize all components with event handlers
        await self.state_machine.initialize()
        await self.risk_manager.initialize()
        await execution_module.initialize(delta_client=self.delta_client, risk_manager=self.risk_manager)
        self.mcp_orchestrator.delta_client = self.delta_client  # For MTF trend_15m when enabled
        await self.learning_system.initialize()
        await self.market_data_service.initialize()
        
        # Initialize model weights from performance metrics if available
        try:
            if self.model_registry.models:
                model_names = list(self.model_registry.models.keys())
                # Create base weights dict with equal weights for all models
                base_weights = {name: 1.0 for name in model_names}
                performance_weights = await self.learning_system.get_updated_model_weights(base_weights)
                if performance_weights:
                    self.model_registry.update_weights_from_performance(performance_weights)
                    logger.info(
                        "agent_model_weights_initialized",
                        service="agent",
                        model_count=len(model_names),
                        weights=performance_weights,
                        message="Model weights initialized from performance metrics"
                    )
                else:
                    # No performance data available, use default equal weights
                    logger.info(
                        "agent_model_weights_using_defaults",
                        service="agent",
                        model_count=len(model_names),
                        message="No performance data available, using default equal weights for all models"
                    )
        except Exception as e:
            logger.warning(
                "agent_model_weights_init_failed",
                service="agent",
                error=str(e),
                error_type=type(e).__name__,
                message="Model weights initialization failed, will use default equal weights",
                exc_info=True
            )
        
        # Register event handlers
        await market_data_handler.register_handlers()
        await feature_handler.register_handlers()
        await model_handler.register_handlers()
        await reasoning_handler.register_handlers()
        # Trading handler bridges DecisionReadyEvent -> RiskApprovedEvent for paper trading
        from agent.events.handlers.trading_handler import TradingEventHandler
        from agent.core.execution import execution_module as exec_module
        trading_handler = TradingEventHandler(
            risk_manager=self.risk_manager,
            delta_client=self.delta_client,
            execution_module=exec_module,
        )
        await trading_handler.register_handlers()
        
        # Initialize WebSocket server for backend connections
        try:
            from agent.api.websocket_server import get_websocket_server
            self.websocket_server = await get_websocket_server(self)
            await self.websocket_server.start()
            logger.info(
                "agent_websocket_server_initialized",
                service="agent",
                host=settings.agent_websocket_host,
                port=settings.agent_websocket_port,
                url=f"ws://{settings.agent_websocket_host}:{settings.agent_websocket_port}"
            )
        except Exception as e:
            logger.warning(
                "agent_websocket_server_init_failed",
                service="agent",
                error=str(e),
                error_type=type(e).__name__,
                message="Agent will continue without WebSocket server, using Redis queue only",
                exc_info=True
            )
            self.websocket_server = None
        
        # Initialize WebSocket client for sending events to backend
        try:
            from agent.api.websocket_client import get_websocket_client
            self.websocket_client = await get_websocket_client()
            if self.websocket_client:
                await self.websocket_client.start()
                logger.info(
                    "agent_websocket_client_initialized",
                    service="agent",
                    url=settings.backend_websocket_url,
                    message="Agent events will be sent via WebSocket and Redis Streams"
                )
            else:
                logger.info(
                    "agent_websocket_client_unavailable",
                    service="agent",
                    message="WebSocket client not available, events will only be sent via Redis Streams"
                )
        except Exception as e:
            logger.warning(
                "agent_websocket_client_init_failed",
                service="agent",
                error=str(e),
                message="Agent will continue without WebSocket client, using Redis Streams only",
                exc_info=True
            )
            self.websocket_client = None
        
        # Initialize state machine
        self.state_machine.current_state = AgentState.INITIALIZING
        await self.context_manager.update_state({"state": AgentState.INITIALIZING})
        
        logger.info("agent_initialized_successfully", service="agent")
        
        await self._apply_start_mode()
        
        # Start market data streaming when monitoring mode is active
        if self.start_mode == "MONITORING":
            # Retry market data streaming startup with exponential backoff
            max_retries = 5
            base_delay = 2.0

            for attempt in range(max_retries):
                try:
                    await self.market_data_service.start_market_data_stream(
                        symbols=[self.default_symbol],
                        interval=self.primary_interval
                    )
                    logger.info(
                        "agent_market_data_stream_started",
                        service="agent",
                        symbols=[self.default_symbol],
                        interval=self.primary_interval,
                        timeframes=self.timeframes,
                        attempt=attempt + 1,
                    )
                    break  # Success, exit retry loop
                except Exception as e:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        "agent_market_data_stream_start_attempt_failed",
                        service="agent",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(e),
                        error_type=type(e).__name__,
                        next_retry_delay_seconds=delay if attempt < max_retries - 1 else None,
                        message="Market data streaming failed, will retry" if attempt < max_retries - 1 else "Market data streaming failed permanently",
                        exc_info=True
                    )

                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                    else:
                        # Final failure - log error but don't crash
                        logger.error(
                            "agent_market_data_stream_start_permanently_failed",
                            service="agent",
                            total_attempts=max_retries,
                            final_error=str(e),
                            error_type=type(e).__name__,
                            message="Agent will continue without market data streaming. Some features may be unavailable.",
                            exc_info=True
                        )
        else:
            logger.info(
                "agent_market_data_stream_skipped",
                service="agent",
                start_mode=self.start_mode,
                message="Start mode disables automatic market data streaming",
            )

        # Start position monitoring loop: check stop/take profit for open positions
        self._position_monitor_task = asyncio.create_task(self._position_monitor_loop())
        logger.info(
            "agent_position_monitor_started",
            service="agent",
            message="Position monitoring loop started for stop loss / take profit",
        )

    async def _position_monitor_loop(self) -> None:
        """Background loop: update position prices and run manage_position for stop/take profit."""
        while self.running:
            try:
                open_positions = execution_module.position_manager.get_all_positions()
                interval_seconds = (
                    getattr(settings, "min_monitor_interval_seconds", 2.0)
                    if open_positions
                    else getattr(settings, "position_monitor_interval_seconds", 15.0)
                )
                await asyncio.sleep(interval_seconds)
                if not self.running:
                    break
                open_positions = execution_module.position_manager.get_all_positions()
                if not open_positions:
                    continue
                max_hold_s = (getattr(settings, "max_position_hold_hours", 24) or 24) * 3600
                now = datetime.now(timezone.utc)
                for symbol in list(open_positions.keys()):
                    if not self.running:
                        break
                    try:
                        position = execution_module.position_manager.get_position(symbol)
                        if position:
                            entry_time = position.get("entry_time")
                            if entry_time is not None:
                                et = entry_time
                                if getattr(et, "tzinfo", None) is None and hasattr(et, "replace"):
                                    et = et.replace(tzinfo=timezone.utc)
                                held_s = (now - et).total_seconds()
                                if held_s > max_hold_s:
                                    await execution_module.close_position(symbol, exit_reason="time_limit")
                                    continue
                        ticker = await self.delta_client.get_ticker(symbol)
                        result = ticker.get("result") or ticker
                        if isinstance(result, dict):
                            close = result.get("close") or result.get("mark_price")
                            if close is not None:
                                current_price = float(close)
                                execution_module.position_manager.update_position(symbol, current_price)
                                await execution_module.manage_position(symbol)
                    except Exception as e:
                        logger.debug(
                            "position_monitor_tick_error",
                            symbol=symbol,
                            error=str(e),
                            service="agent",
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "position_monitor_loop_error",
                    error=str(e),
                    service="agent",
                    exc_info=True,
                )

    async def shutdown(self):
        """Shutdown agent."""
        logger.info(
            "agent_shutting_down",
            service="agent",
            environment=settings.environment,
        )
        self.running = False

        # Cancel position monitoring loop
        if getattr(self, "_position_monitor_task", None):
            self._position_monitor_task.cancel()
            try:
                await self._position_monitor_task
            except asyncio.CancelledError:
                pass
            self._position_monitor_task = None

        # Shutdown WebSocket server
        if hasattr(self, 'websocket_server') and self.websocket_server:
            try:
                await self.websocket_server.stop()
            except Exception as e:
                logger.warning(
                    "agent_websocket_server_shutdown_error",
                    service="agent",
                    error=str(e)
                )
        
        # Shutdown WebSocket client
        if hasattr(self, 'websocket_client') and self.websocket_client:
            try:
                await self.websocket_client.stop()
            except Exception as e:
                logger.warning(
                    "agent_websocket_client_shutdown_error",
                    service="agent",
                    error=str(e)
                )
        
        # Shutdown all components
        await self.market_data_service.shutdown()
        await self.learning_system.shutdown()
        await execution_module.shutdown()
        await self.risk_manager.shutdown()
        await self.model_registry.shutdown()
        await self.feature_server_api.shutdown()
        await self.mcp_orchestrator.shutdown()
        await event_bus.shutdown()
        
        logger.info(
            "agent_shut_down",
            service="agent",
            environment=settings.environment,
        )
    
    def _check_market_data_health(self) -> bool:
        """Check if market data service is healthy.

        Returns:
            True if market data service appears healthy, False otherwise
        """
        try:
            # Check if WebSocket is connected
            websocket_connected = getattr(self.market_data_service, '_websocket_connected', False)

            # Check if streaming is running
            streaming_running = getattr(self.market_data_service, 'streaming_running', False)

            # Check if we have recent ticker data (within last 5 minutes)
            last_ticker_time = None
            if hasattr(self.market_data_service, '_last_tick_time'):
                last_times = self.market_data_service._last_tick_time
                if last_times and self.default_symbol in last_times:
                    last_ticker_time = last_times[self.default_symbol]

            ticker_recent = last_ticker_time and (time.time() - last_ticker_time.timestamp()) < 300

            # Consider healthy if WebSocket connected OR streaming running OR recent ticker data
            return websocket_connected or streaming_running or ticker_recent

        except Exception as e:
            logger.warning(
                "market_data_health_check_failed",
                service="agent",
                error=str(e),
                message="Could not check market data service health"
            )
            return False

    async def _apply_start_mode(self) -> None:
        """Apply configured start mode to the state machine."""
        if self.start_mode == "EMERGENCY_STOP":
            await self.state_machine._transition_to(
                AgentState.EMERGENCY_STOP,
                "Agent configured to start in EMERGENCY_STOP mode"
            )
            return
        
        if self.start_mode == "PAUSED":
            await self.state_machine._transition_to(
                AgentState.OBSERVING,
                "Agent configured to start in PAUSED mode"
            )
            return
        
        await self.state_machine._transition_to(
            AgentState.OBSERVING,
            "Initialization complete"
        )

        # Explicitly publish a state update event to ensure frontend gets the initial state
        # This is in addition to the StateTransitionEvent that _transition_to() emits
        from agent.events.schemas import StateTransitionEvent
        from agent.events.event_bus import event_bus

        try:
            initial_state_event = StateTransitionEvent(
                source="intelligent_agent",
                payload={
                    "from_state": "INITIALIZING",
                    "to_state": "OBSERVING",
                    "reason": "Agent initialization completed successfully",
                    "timestamp": datetime.utcnow()
                }
            )
            await event_bus.publish(initial_state_event)
            logger.info(
                "agent_initial_state_broadcast",
                service="agent",
                state="OBSERVING",
                event_id=initial_state_event.event_id,
                message="Initial agent state broadcast to ensure frontend visibility"
            )
        except Exception as e:
            logger.warning(
                "agent_initial_state_broadcast_failed",
                service="agent",
                error=str(e),
                message="Failed to broadcast initial state, but agent continues"
            )
    
    async def start(self):
        """Start agent main loop."""
        logger.info("agent_start_method_called")
        self.running = True
        logger.info("agent_running_set_to_true")

        # Start command handler (for backward compatibility)
        logger.info("agent_creating_command_task")
        command_task = asyncio.create_task(self._command_handler())
        logger.info("agent_command_task_created")

        # Start event bus consumption for market data processing
        event_task = asyncio.create_task(event_bus.start_consuming())

        # Start periodic monitoring task
        monitoring_task = asyncio.create_task(self._periodic_monitoring())

        try:
            logger.info("agent_about_to_gather_tasks")
            await asyncio.gather(command_task, event_task, monitoring_task)
            logger.info("agent_gather_completed")
        except asyncio.CancelledError:
            pass
    
    async def _command_handler(self):
        """Consume commands from Redis queue and process them."""
        from agent.core.redis_config import get_redis
        logger.info("agent_command_handler_started", queue=self.command_queue)
        count = 0
        while self.running:
            try:
                redis_client = await get_redis()
                if redis_client:
                    # BRPOP blocks for 1s - FIFO (backend LPUSH, we BRPOP)
                    result = await redis_client.brpop(self.command_queue, timeout=1)
                    if result:
                        _, raw = result
                        command = json.loads(raw)
                        await self._process_command(command)
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                count += 1
                if count % 30 == 0:
                    logger.warning(
                        "agent_command_handler_error",
                        error=str(e),
                        count=count,
                        service="agent"
                    )
                await asyncio.sleep(1)
    
    async def _process_command(self, command):
        """Process command from backend."""
        request_id = command.get("request_id") or str(uuid.uuid4())
        cmd = command.get("command")
        params = command.get("parameters", {})

        try:
            if cmd == "get_status":
                result = await self._handle_get_status()
                payload = result.get("data", result)
                await self._send_response(request_id, payload)
            elif cmd == "predict":
                result = await self._handle_predict(params)
                await self._send_response(request_id, result)
            elif cmd == "execute_trade":
                result = await self._handle_execute_trade(params)
                await self._send_response(request_id, result)
            elif cmd == "control":
                await self._send_response(
                    request_id, {"success": True, "message": "Control processed"}
                )
            else:
                await self._send_response(
                    request_id,
                    {"success": True, "message": f"Command '{cmd}' processed"},
                )
        except Exception as e:
            logger.error(
                "agent_command_processing_error",
                error=str(e),
                cmd=cmd,
                request_id=request_id,
                exc_info=True,
                service="agent",
            )
            await self._send_response(request_id, {"success": False, "error": str(e)})
    
    async def _handle_predict(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle prediction request."""
        symbol = params.get("symbol", self.default_symbol)
        context = params.get("context", {})
        
        decision = await self.mcp_orchestrator.get_trading_decision(
            symbol=symbol,
            market_context=context
        )
        
        return {"success": True, "data": decision}
    
    async def _handle_execute_trade(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle trade execution request via execution engine."""
        symbol = params.get("symbol", self.default_symbol)
        side_raw = params.get("side", "BUY")
        side = side_raw.lower() if isinstance(side_raw, str) else "buy"
        quantity = float(params.get("quantity", 0))
        order_type = (params.get("order_type") or "MARKET").lower()
        price = float(params["price"]) if params.get("price") is not None else None
        stop_loss = float(params["stop_loss"]) if params.get("stop_loss") is not None else None
        take_profit = float(params["take_profit"]) if params.get("take_profit") is not None else None

        if quantity <= 0:
            return {
                "success": False,
                "data": None,
                "error": "Invalid quantity"
            }

        trade = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": "market" if order_type == "MARKET" else order_type,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

        result = await execution_module.execute_trade(trade)

        if not result.success:
            return {
                "success": False,
                "data": None,
                "error": result.error_message or "Trade execution failed"
            }

        fill_price = result.details.get("average_fill_price") or price or 0
        order_id = result.order_id or str(uuid.uuid4())[:8]
        trade_id = f"trade_{order_id}_{datetime.utcnow().timestamp()}"

        # Publish OrderFillEvent for backend persistence and WebSocket broadcast
        from agent.events.schemas import OrderFillEvent
        from agent.events.event_bus import event_bus
        order_fill = OrderFillEvent(
            source="intelligent_agent",
            payload={
                "order_id": order_id,
                "trade_id": trade_id,
                "symbol": symbol,
                "side": side_raw if isinstance(side_raw, str) else side.upper(),
                "quantity": quantity,
                "fill_price": fill_price,
                "timestamp": datetime.now(timezone.utc),
            },
        )
        await event_bus.publish(order_fill)

        if settings.paper_trading_mode:
            from agent.core.paper_trade_logger import paper_trade_logger
            paper_trade_logger.log_trade(
                trade_id=trade_id,
                symbol=symbol,
                side=side_raw if isinstance(side_raw, str) else side.upper(),
                quantity=quantity,
                fill_price=fill_price,
                order_id=order_id,
            )

        return {
            "success": True,
            "data": {
                "trade_id": trade_id,
                "status": "EXECUTED",
                "symbol": symbol,
                "side": side_raw if isinstance(side_raw, str) else side.upper(),
                "quantity": quantity,
                "price": fill_price,
                "order_id": order_id,
            }
        }
    
    async def _handle_get_status(self) -> Dict[str, Any]:
        """Handle status request with detailed health information."""
        logger.info("agent_handling_get_status", message="Processing get_status command")

        # Check if MCP orchestrator is initialized
        if not hasattr(self, 'mcp_orchestrator') or self.mcp_orchestrator is None:
            logger.warning("mcp_orchestrator_not_initialized")
            health = {"mcp_orchestrator": {"components": {}}}
        else:
            try:
                # Add timeout to prevent hanging health checks
                health = await asyncio.wait_for(
                    self.mcp_orchestrator.get_health_status(),
                    timeout=2.0  # 2 second timeout for health checks
                )
            except asyncio.TimeoutError:
                logger.warning("mcp_orchestrator_health_timeout", message="Health check timed out, using fallback")
                health = {"mcp_orchestrator": {"components": {}}}
            except Exception as e:
                logger.error("mcp_orchestrator_health_failed", error=str(e), exc_info=True)
                health = {"mcp_orchestrator": {"components": {}}}

        # Extract detailed health information from nested MCP orchestrator structure
        mcp_components = health.get("mcp_orchestrator", {}).get("components", {})

        # Provide fallback status if components are missing
        if not mcp_components.get("feature_server"):
            mcp_components["feature_server"] = {
                "status": "unknown",
                "note": "Feature server health check failed or not initialized"
            }

        if not mcp_components.get("model_registry"):
            mcp_components["model_registry"] = {
                "status": "unknown",
                "note": "Model registry health check failed or not initialized"
            }

        if not mcp_components.get("reasoning_engine"):
            mcp_components["reasoning_engine"] = {
                "status": "unknown",
                "note": "Reasoning engine health check failed or not initialized"
            }
        feature_server_health = mcp_components.get("feature_server", {})
        model_registry_health = mcp_components.get("model_registry", {})
        reasoning_engine_health = mcp_components.get("reasoning_engine", {})
        
        # Extract delta_exchange status from feature_server (which includes market_data_service)
        delta_exchange_status = {}
        if feature_server_health and isinstance(feature_server_health, dict):
            market_data_service = feature_server_health.get("market_data_service", {})
            if market_data_service and isinstance(market_data_service, dict):
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
                    "latency_ms": None,
                    "note": "Market data service not available in feature server health"
                }
        else:
            delta_exchange_status = {
                "status": "unknown",
                "latency_ms": None,
                "note": "Feature server health not available"
            }
        
        # Extract model_nodes status from model_registry
        model_nodes_status = {}
        if model_registry_health and isinstance(model_registry_health, dict):
            total_models = model_registry_health.get("total_models", 0)
            healthy_models = model_registry_health.get("healthy_models", 0)
            registry_health = model_registry_health.get("registry_health", "unknown")
            discovery_info = model_registry_health.get("discovery", {}) or {}
            discovery_attempted = discovery_info.get("discovery_attempted", False)
            failed_models = discovery_info.get("failed_models", 0)
            
            # Use status from registry if available (it's now properly mapped)
            registry_status = model_registry_health.get("status", "unknown")
            model_status = registry_status
            note = None
            
            # Override status for specific cases to provide better information
            # Use actual total_models from registry (which is always accurate)
            # If we have models, discovery must have been attempted (even if summary says otherwise)
            if total_models == 0:
                # No models loaded - determine why
                if discovery_attempted and failed_models > 0:
                    model_status = "down"
                    note = "Model discovery attempted but no models loaded successfully."
                    discovery_reason = "failed_models"
                elif discovery_attempted:
                    model_status = "unknown"
                    note = "Model discovery ran but no model files were found."
                    discovery_reason = "no_model_files_found"
                else:
                    model_status = "unknown"
                    note = "Model discovery disabled; no ML models were loaded."
                    discovery_reason = "discovery_disabled"
                
                logger.warning(
                    "model_nodes_discovery_result",
                    service="agent",
                    component="model_registry",
                    session_id=self.session_id,
                    total_models=total_models,
                    healthy_models=healthy_models,
                    discovery_attempted=discovery_attempted,
                    failed_models=failed_models,
                    discovery_reason=discovery_reason,
                    status=model_status,
                    note=note,
                )
            elif healthy_models == 0 and total_models > 0:
                # Models loaded but all unhealthy
                model_status = "down"
                note = f"{total_models} model(s) loaded but all are unhealthy."
            else:
                # Models loaded and at least some are healthy
                # If discovery_attempted is false but we have models, it's a data inconsistency - don't log warning
                # The registry state is the source of truth
                if total_models > 0 and not discovery_attempted:
                    # This shouldn't happen, but if it does, we know discovery actually happened
                    # since we have models. Don't log a warning since models are working.
                    pass
            # Otherwise use the status from registry (which is properly mapped)
            
            model_nodes_status = {
                "status": model_status,
                "healthy_models": healthy_models,
                "total_models": total_models,
                "registry_health": registry_health,
                "discovery": discovery_info,
            }
            if note:
                model_nodes_status["note"] = note
        else:
            model_nodes_status = {
                "status": "unknown",
                "healthy_models": 0,
                "total_models": 0,
                "note": "Model registry health status not available"
            }
            logger.warning(
                "model_nodes_status_missing",
                service="agent",
                component="model_registry",
                session_id=self.session_id,
                note="Model registry health status not available",
            )
        
        # Build comprehensive health response with fallbacks for unknown status
        feature_server_status = "unknown"
        if feature_server_health and isinstance(feature_server_health, dict):
            feature_server_status = feature_server_health.get("status", "unknown")
            if feature_server_status == "unknown":
                # If we have health data but status is unknown, try to infer status
                feature_count = feature_server_health.get("feature_registry_count", 0)
                if feature_count > 0:
                    feature_server_status = "up"
                    feature_server_health["status"] = "up"

        model_nodes_status_final = model_nodes_status.copy() if model_nodes_status else {}
        if isinstance(model_nodes_status_final, dict) and model_nodes_status_final.get("status") == "unknown" and model_nodes_status_final.get("total_models", 0) > 0:
            # If we have models but status is unknown, assume they're working
            model_nodes_status_final["status"] = "up"

        reasoning_engine_status = "unknown"
        if reasoning_engine_health and isinstance(reasoning_engine_health, dict):
            reasoning_engine_status = reasoning_engine_health.get("status", "unknown")
            if reasoning_engine_status == "unknown":
                # Reasoning engine should be available if MCP orchestrator initialized
                reasoning_engine_status = "up"
                reasoning_engine_health["status"] = "up"

        # Apply final status inference to ensure consistency
        detailed_health = {
            "feature_server": dict(feature_server_health),
            "model_nodes": dict(model_nodes_status_final),
            "delta_exchange": dict(delta_exchange_status),
            "reasoning_engine": dict(reasoning_engine_health)
        }

        # Final status inference pass - ensure statuses are properly set
        if detailed_health["feature_server"].get("status") == "unknown":
            feature_count = detailed_health["feature_server"].get("feature_registry_count", 0)
            if feature_count > 0:
                detailed_health["feature_server"]["status"] = "up"
                detailed_health["feature_server"]["note"] = f"Inferred healthy status from {feature_count} registered features"

        if detailed_health["model_nodes"].get("status") == "unknown":
            healthy_count = detailed_health["model_nodes"].get("healthy_models", 0)
            total_count = detailed_health["model_nodes"].get("total_models", 0)
            if total_count > 0:
                if healthy_count > 0:
                    detailed_health["model_nodes"]["status"] = "up"
                elif healthy_count == 0 and total_count > 0:
                    detailed_health["model_nodes"]["status"] = "down"
                detailed_health["model_nodes"]["note"] = f"Inferred status from {healthy_count}/{total_count} healthy models"

        if detailed_health["delta_exchange"].get("status") == "unknown":
            circuit_breaker = detailed_health["delta_exchange"].get("circuit_breaker", {})
            if isinstance(circuit_breaker, dict):
                cb_state = circuit_breaker.get("state")
                if cb_state == "CLOSED":
                    detailed_health["delta_exchange"]["status"] = "up"
                    detailed_health["delta_exchange"]["note"] = "Inferred healthy status from circuit breaker state"
                elif cb_state == "OPEN":
                    detailed_health["delta_exchange"]["status"] = "down"
                    detailed_health["delta_exchange"]["note"] = "Circuit breaker is open - service temporarily unavailable"

        if detailed_health["reasoning_engine"].get("status") == "unknown":
            # Reasoning engine is typically available if agent is running and initialized
            vector_store_available = detailed_health["reasoning_engine"].get("vector_store_available", None)
            if vector_store_available is not None:
                detailed_health["reasoning_engine"]["status"] = "up"
                detailed_health["reasoning_engine"]["note"] = "Inferred healthy status from reasoning engine data availability"

        # Add overall status
        detailed_health["overall_status"] = health.get("overall_status", "unknown")

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
    
    async def _handle_register_models(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle manual model registration requests."""
        model_names = params.get("models")
        if model_names is not None and not isinstance(model_names, list):
            return {
                "success": False,
                "error": "models parameter must be a list of model names"
            }
        
        registration_result = self.model_registry.register_pending_models(model_names)
        pending_after = self.model_registry.list_pending_models()
        return {
            "success": True,
            "data": {
                "registered": registration_result.get("registered", []),
                "not_found": registration_result.get("not_found", []),
                "pending": pending_after,
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
    
    async def _periodic_monitoring(self):
        """Periodic monitoring task to log agent status and decision generation metrics."""
        import time
        
        last_decision_time = None
        last_candle_time = None
        
        # Subscribe to decision ready events to track last decision time
        async def track_decision(event):
            nonlocal last_decision_time
            last_decision_time = time.time()
        
        # Subscribe to candle closed events to track last candle time
        async def track_candle(event):
            nonlocal last_candle_time
            last_candle_time = time.time()
        
        from agent.events.schemas import DecisionReadyEvent, CandleClosedEvent
        event_bus.subscribe(EventType.DECISION_READY, track_decision)
        event_bus.subscribe(EventType.CANDLE_CLOSED, track_candle)
        
        while self.running:
            try:
                await asyncio.sleep(300)  # Log every 5 minutes

                current_state = self.state_machine.current_state.value
                time_since_last_decision = None
                time_since_last_candle = None

                if last_decision_time:
                    time_since_last_decision = time.time() - last_decision_time

                if last_candle_time:
                    time_since_last_candle = time.time() - last_candle_time

                # Check market data service health
                market_data_healthy = self._check_market_data_health()
                websocket_connected = getattr(self.market_data_service, '_websocket_connected', False)
                streaming_running = getattr(self.market_data_service, 'streaming_running', False)

                logger.info(
                    "agent_periodic_status",
                    service="agent",
                    state=current_state,
                    time_since_last_decision_seconds=time_since_last_decision,
                    time_since_last_candle_seconds=time_since_last_candle,
                    market_data_healthy=market_data_healthy,
                    websocket_connected=websocket_connected,
                    streaming_running=streaming_running,
                    message="Agent periodic status check - decision generation monitoring"
                )

                # Log warning if no decisions generated in last 30 minutes
                if time_since_last_decision and time_since_last_decision > 1800:
                    logger.warning(
                        "agent_no_decisions_generated",
                        service="agent",
                        state=current_state,
                        time_since_last_decision_minutes=int(time_since_last_decision / 60),
                        message="No decisions generated in last 30 minutes - check candle close events and decision pipeline"
                    )

                # Log warning if no candle close events in last 20 minutes
                if time_since_last_candle and time_since_last_candle > 1200:
                    logger.warning(
                        "agent_no_candle_closes",
                        service="agent",
                        state=current_state,
                        time_since_last_candle_minutes=int(time_since_last_candle / 60),
                        websocket_connected=websocket_connected,
                        streaming_running=streaming_running,
                        message="No candle close events detected in last 20 minutes - check market data service"
                    )

                    # Try to restart market data streaming if it's not running
                    if self.start_mode == "MONITORING" and not streaming_running:
                        logger.info(
                            "agent_attempting_market_data_restart",
                            service="agent",
                            message="Attempting to restart market data streaming due to no recent candle events"
                        )
                        try:
                            await self.market_data_service.start_market_data_stream(
                                symbols=[self.default_symbol],
                                interval=self.primary_interval
                            )
                            logger.info(
                                "agent_market_data_stream_restarted",
                                service="agent",
                                symbols=[self.default_symbol],
                                interval=self.primary_interval,
                            )
                        except Exception as e:
                            logger.error(
                                "agent_market_data_stream_restart_failed",
                                service="agent",
                                error=str(e),
                                error_type=type(e).__name__,
                                message="Failed to restart market data streaming",
                                exc_info=True
                            )
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "agent_periodic_monitoring_error",
                    service="agent",
                    error=str(e),
                    exc_info=True
                )
                await asyncio.sleep(60)  # Wait before retrying on error

    async def _send_response(self, request_id: str, payload: Dict[str, Any], ttl: int = 120):
        """Send response back to backend via Redis key-value store.
        
        Backend polls for responses using get_response() which reads from response:{request_id} key.
        TTL ensures responses are automatically cleaned up after expiration.
        """
        response = dict(payload)
        response["request_id"] = request_id
        logger.info("agent_getting_redis_connection", request_id=request_id)
        redis = await get_redis()
        logger.info("agent_redis_connection_result", request_id=request_id, redis_available=redis is not None)

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
            await redis.setex(
                f"response:{request_id}",
                ttl,
                json.dumps(response, default=_json_serializer),
            )
            logger.info(
                "agent_response_sent",
                request_id=request_id,
                ttl=ttl,
                service="agent",
                message=f"Response sent for request {request_id}"
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
    print("AGENT: Starting main function")
    agent = IntelligentAgent()
    print("AGENT: IntelligentAgent created")

    try:
        logger.info("agent_about_to_initialize_mcp_orchestrator")
        # Initialize the global MCP orchestrator first
        from agent.core.mcp_orchestrator import mcp_orchestrator
        await mcp_orchestrator.initialize()
        logger.info("agent_mcp_orchestrator_initialized")

        # Update agent's orchestrator reference to the initialized instance
        agent.mcp_orchestrator = mcp_orchestrator

        logger.info("agent_about_to_call_initialize")
        await agent.initialize()
        logger.info("agent_initialize_completed")

        logger.info("agent_about_to_call_start")
        await agent.start()
        logger.info("agent_start_completed")

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

