"""
Agent Event Subscriber - Bridges Redis Streams to WebSocket.

Subscribes to agent events from Redis Streams and broadcasts them to
frontend clients via WebSocket.
"""

import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from backend.core.redis import get_redis
from backend.api.websocket.manager import websocket_manager
from backend.core.logging import log_error_with_context
from backend.services.trade_persistence_service import trade_persistence_service
from decimal import Decimal

logger = structlog.get_logger()


class AgentEventSubscriber:
    """Subscribes to agent events and broadcasts via WebSocket."""

    def __init__(
        self,
        stream_name: str = "trading_agent_events",
        consumer_group: str = "backend_websocket_bridge"
    ):
        """Initialize agent event subscriber.
        
        Args:
            stream_name: Redis stream name to subscribe to
            consumer_group: Consumer group name for Redis Streams
        """
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = f"backend_ws_bridge_{id(self)}"
        self.running = False
        self._consuming_task: Optional[asyncio.Task] = None
        self._redis_client: Optional[Redis] = None

    async def initialize(self):
        """Initialize Redis consumer group."""
        try:
            redis = await get_redis()
            if redis is None:
                logger.warning(
                    "agent_event_subscriber_redis_unavailable",
                    service="backend",
                    message="Redis unavailable, event subscription disabled"
                )
                return

            self._redis_client = redis

            # Create consumer group (ignore if already exists)
            try:
                await redis.xgroup_create(
                    name=self.stream_name,
                    groupname=self.consumer_group,
                    id="0",  # Start from beginning
                    mkstream=True  # Create stream if it doesn't exist
                )
                logger.info(
                    "agent_event_subscriber_consumer_group_created",
                    service="backend",
                    stream=self.stream_name,
                    group=self.consumer_group
                )
            except ResponseError as e:
                # Consumer group already exists, which is fine
                if "BUSYGROUP" not in str(e):
                    raise
                logger.debug(
                    "agent_event_subscriber_consumer_group_exists",
                    service="backend",
                    stream=self.stream_name,
                    group=self.consumer_group
                )

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_initialize_error",
                error=e,
                component="agent_event_subscriber",
                stream=self.stream_name,
                group=self.consumer_group
            )
            # Don't raise - allow graceful degradation

    async def start(self):
        """Start consuming events from Redis Stream."""
        if self.running:
            logger.warning(
                "agent_event_subscriber_already_running",
                service="backend"
            )
            return

        if self._redis_client is None:
            redis = await get_redis()
            if redis is None:
                logger.warning(
                    "agent_event_subscriber_start_redis_unavailable",
                    service="backend",
                    message="Cannot start: Redis unavailable"
                )
                return
            self._redis_client = redis

        self.running = True
        self._consuming_task = asyncio.create_task(self._consume_loop())
        logger.info(
            "agent_event_subscriber_started",
            service="backend",
            stream=self.stream_name,
            consumer_group=self.consumer_group,
            consumer_name=self.consumer_name
        )

    async def stop(self):
        """Stop consuming events."""
        if not self.running:
            return

        self.running = False

        if self._consuming_task:
            self._consuming_task.cancel()
            try:
                await self._consuming_task
            except asyncio.CancelledError:
                pass

        logger.info(
            "agent_event_subscriber_stopped",
            service="backend",
            stream=self.stream_name
        )

    async def _consume_loop(self):
        """Main loop to read from Redis stream."""
        while self.running:
            try:
                if self._redis_client is None:
                    await asyncio.sleep(1)
                    continue

                # Read pending messages first (in case of reconnection)
                pending = await self._redis_client.xpending_range(
                    name=self.stream_name,
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    min="-",
                    max="+",
                    count=10
                )

                # Process pending messages
                for msg in pending:
                    message_id = msg["message_id"]
                    try:
                        messages = await self._redis_client.xclaim(
                            name=self.stream_name,
                            groupname=self.consumer_group,
                            consumername=self.consumer_name,
                            min_idle_time=60000,  # 60 seconds
                            message_ids=[message_id]
                        )
                        for msg_id, msg_data in messages:
                            await self._process_message(msg_id, msg_data)
                    except Exception as e:
                        logger.warning(
                            "agent_event_subscriber_pending_message_error",
                            service="backend",
                            message_id=message_id,
                            error=str(e)
                        )

                # Read new messages from stream
                messages = await self._redis_client.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},  # Read new messages
                    count=10,  # Batch size
                    block=1000  # Block for 1 second
                )

                for stream_name, stream_messages in messages:
                    for message_id, message_data in stream_messages:
                        await self._process_message(message_id, message_data)

            except asyncio.CancelledError:
                logger.info(
                    "agent_event_subscriber_consume_loop_cancelled",
                    service="backend"
                )
                raise
            except Exception as e:
                log_error_with_context(
                    "agent_event_subscriber_consume_loop_error",
                    error=e,
                    component="agent_event_subscriber",
                    stream=self.stream_name
                )
                # Wait before retrying
                await asyncio.sleep(1)

    async def _process_message(self, message_id: str, message_data: Dict[str, bytes]):
        """Process a single message from the stream.
        
        Args:
            message_id: Message ID from Redis stream
            message_data: Raw message data from stream
        """
        try:
            # Decode message data
            decoded_data = {}
            for key, value in message_data.items():
                if isinstance(value, bytes):
                    decoded_data[key.decode("utf-8")] = value.decode("utf-8")
                else:
                    decoded_data[key] = value

            # Deserialize event JSON
            if "data" in decoded_data:
                event_dict = json.loads(decoded_data["data"])
            elif len(decoded_data) == 1:
                # If only one field, it's likely the serialized event
                first_key = list(decoded_data.keys())[0]
                event_dict = json.loads(decoded_data[first_key])
            else:
                # Use decoded_data directly
                event_dict = decoded_data

            # Extract event type
            event_type = event_dict.get("event_type")
            payload = event_dict.get("payload", {})
            
            # Log event receipt for debugging
            logger.debug(
                "agent_event_subscriber_event_received",
                service="backend",
                event_type=event_type,
                message_id=message_id
            )

            if not event_type:
                logger.warning(
                    "agent_event_subscriber_missing_event_type",
                    service="backend",
                    message_id=message_id
                )
                return

            # Dispatch to appropriate handler
            await self._handle_event(event_type, payload)

            # Acknowledge message
            if self._redis_client:
                await self._redis_client.xack(
                    self.stream_name,
                    self.consumer_group,
                    message_id
                )

        except json.JSONDecodeError as e:
            logger.error(
                "agent_event_subscriber_json_decode_error",
                service="backend",
                message_id=message_id,
                error=str(e)
            )
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_process_message_error",
                error=e,
                component="agent_event_subscriber",
                message_id=message_id
            )

    async def _handle_event(self, event_type: str, payload: Dict[str, Any]):
        """Handle different event types.
        
        Args:
            event_type: Type of event
            payload: Event payload
        """
        try:
            if event_type == "decision_ready":
                await self._handle_decision_ready(payload)
            elif event_type == "state_transition":
                await self._handle_state_transition(payload)
            elif event_type == "order_fill":
                await self._handle_order_fill(payload)
            elif event_type == "position_closed":
                await self._handle_position_closed(payload)
            elif event_type == "model_prediction_complete":
                await self._handle_model_prediction_complete(payload)
            elif event_type == "market_tick":
                await self._handle_market_tick(payload)
            # Add more event handlers as needed

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_handle_event_error",
                error=e,
                component="agent_event_subscriber",
                event_type=event_type
            )

    async def _handle_decision_ready(self, payload: Dict[str, Any]):
        """Handle DecisionReadyEvent.
        
        Args:
            payload: DecisionReadyEvent payload
        """
        try:
            signal = payload.get("signal", "HOLD")
            confidence = payload.get("confidence", 0.0)
            symbol = payload.get("symbol", "BTCUSD")
            reasoning_chain = payload.get("reasoning_chain", {})
            
            # Extract timestamp - check multiple possible locations
            timestamp = payload.get("timestamp")
            if not timestamp and reasoning_chain:
                # Check if timestamp is in reasoning_chain
                if isinstance(reasoning_chain, dict):
                    timestamp = reasoning_chain.get("timestamp")
                    if not timestamp:
                        # Check in market_context
                        market_context = reasoning_chain.get("market_context", {})
                        if isinstance(market_context, dict):
                            timestamp = market_context.get("timestamp")

            # Convert confidence from 0-1 to 0-100 range if needed
            if 0.0 <= confidence <= 1.0:
                confidence = confidence * 100.0

            # Extract reasoning chain steps
            reasoning_steps = reasoning_chain.get("steps", [])
            conclusion = reasoning_chain.get("conclusion", "")
            
            # Extract market context and model predictions from reasoning_chain
            market_context = reasoning_chain.get("market_context", {})
            model_predictions = reasoning_chain.get("model_predictions", [])

            # Extract model consensus from market_context
            model_consensus = market_context.get("model_consensus", [])
            
            # Extract individual model reasoning from model_predictions
            individual_model_reasoning = []
            if isinstance(model_predictions, list):
                for pred in model_predictions:
                    if isinstance(pred, dict):
                        model_name = pred.get("model_name", "Unknown")
                        reasoning = pred.get("reasoning", "")
                        pred_confidence = pred.get("confidence", 0.0)
                        
                        # Convert confidence to 0-100 if needed
                        if 0.0 <= pred_confidence <= 1.0:
                            pred_confidence = pred_confidence * 100.0
                        
                        individual_model_reasoning.append({
                            "model_name": model_name,
                            "reasoning": reasoning,
                            "confidence": pred_confidence
                        })

            # Handle timestamp - ensure it's properly formatted
            formatted_timestamp = timestamp
            if timestamp:
                if isinstance(timestamp, datetime):
                    formatted_timestamp = timestamp.isoformat()
                elif isinstance(timestamp, str):
                    # Already a string, use as-is
                    formatted_timestamp = timestamp
                else:
                    # Fallback to current time if invalid
                    formatted_timestamp = datetime.utcnow().isoformat()
            else:
                # No timestamp provided, use current time
                formatted_timestamp = datetime.utcnow().isoformat()

            # Format signal data for frontend
            signal_data = {
                "signal": signal,
                "confidence": confidence,
                "symbol": symbol,
                "model_consensus": model_consensus,
                "reasoning_chain": reasoning_steps,
                "individual_model_reasoning": individual_model_reasoning,
                "agent_decision_reasoning": conclusion,
                "timestamp": formatted_timestamp
            }

            # Broadcast via WebSocket
            await websocket_manager.broadcast(
                {"type": "signal_update", "data": signal_data},
                channel="signal_update"
            )

            logger.info(
                "agent_event_subscriber_decision_ready_broadcast",
                service="backend",
                signal=signal,
                confidence=confidence,
                symbol=symbol,
                timestamp=formatted_timestamp
            )

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_decision_ready_error",
                error=e,
                component="agent_event_subscriber"
            )

    async def _handle_state_transition(self, payload: Dict[str, Any]):
        """Handle StateTransitionEvent.
        
        Args:
            payload: StateTransitionEvent payload
        """
        try:
            to_state = payload.get("to_state", "UNKNOWN")
            reason = payload.get("reason", "")
            timestamp = payload.get("timestamp")

            # Format state data for frontend
            state_data = {
                "state": to_state,
                "reason": reason,
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
            }

            # Broadcast via WebSocket
            await websocket_manager.broadcast(
                {"type": "agent_state", "data": state_data},
                channel="agent_state"
            )

            logger.debug(
                "agent_event_subscriber_state_transition_broadcast",
                service="backend",
                state=to_state,
                reason=reason
            )

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_state_transition_error",
                error=e,
                component="agent_event_subscriber"
            )

    async def _handle_order_fill(self, payload: Dict[str, Any]):
        """Handle OrderFillEvent.
        
        Args:
            payload: OrderFillEvent payload
        """
        try:
            order_id = payload.get("order_id", "")
            trade_id = payload.get("trade_id", "")
            symbol = payload.get("symbol", "")
            side = payload.get("side", "")
            quantity = payload.get("quantity", 0.0)
            fill_price = payload.get("fill_price", 0.0)
            timestamp = payload.get("timestamp")
            
            # Convert timestamp to datetime if it's a string
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except Exception:
                    timestamp = datetime.utcnow()
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.utcnow()

            # Persist trade and position to database
            try:
                # Calculate stop loss and take profit (using same logic as execution module)
                from backend.core.config import settings
                stop_loss_pct = settings.stop_loss_percentage
                take_profit_pct = settings.take_profit_percentage
                
                if side.upper() == "BUY":
                    stop_loss = fill_price * (1 - stop_loss_pct) if stop_loss_pct else None
                    take_profit = fill_price * (1 + take_profit_pct) if take_profit_pct else None
                else:  # SELL
                    stop_loss = fill_price * (1 + stop_loss_pct) if stop_loss_pct else None
                    take_profit = fill_price * (1 - take_profit_pct) if take_profit_pct else None
                
                persistence_result = await trade_persistence_service.create_trade_and_position(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price,
                    order_type="MARKET",
                    reasoning_chain_id=None,  # Could be enhanced to include this
                    model_predictions=None,  # Could be enhanced to include this
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    executed_at=timestamp
                )
                
                logger.info(
                    "trade_persisted_to_database",
                    service="backend",
                    trade_id=trade_id,
                    position_id=persistence_result.get("position_id"),
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price
                )
            except Exception as persistence_error:
                # Log error but don't fail the entire handler
                log_error_with_context(
                    "trade_persistence_failed",
                    error=persistence_error,
                    component="agent_event_subscriber",
                    trade_id=trade_id,
                    symbol=symbol
                )

            # Format trade data for frontend
            trade_data = {
                "order_id": order_id,
                "trade_id": trade_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": fill_price,
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
            }

            # Broadcast via WebSocket
            await websocket_manager.broadcast(
                {"type": "trade_executed", "data": trade_data},
                channel="trade_executed"
            )

            logger.debug(
                "agent_event_subscriber_order_fill_broadcast",
                service="backend",
                order_id=order_id,
                symbol=symbol,
                side=side
            )
            
            # Broadcast portfolio update after trade execution
            await self._broadcast_portfolio_update()

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_order_fill_error",
                error=e,
                component="agent_event_subscriber"
            )

    async def _handle_position_closed(self, payload: Dict[str, Any]):
        """Handle PositionClosedEvent.
        
        Args:
            payload: PositionClosedEvent payload
        """
        try:
            position_id = payload.get("position_id", "")
            symbol = payload.get("symbol", "")
            entry_price = payload.get("entry_price", 0.0)
            exit_price = payload.get("exit_price", 0.0)
            pnl = payload.get("pnl", 0.0)
            exit_reason = payload.get("exit_reason", "unknown")
            timestamp = payload.get("timestamp")
            
            # Convert timestamp to datetime if needed
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except Exception:
                    timestamp = datetime.utcnow()
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.utcnow()
            
            # Update position in database
            try:
                close_result = await trade_persistence_service.close_position(
                    position_id=position_id,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl=pnl,
                    closed_at=timestamp
                )
                
                if close_result.get("success"):
                    logger.info(
                        "position_closed_in_database",
                        service="backend",
                        position_id=position_id,
                        symbol=symbol,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl=pnl,
                        exit_reason=exit_reason,
                        is_profit=close_result.get("is_profit"),
                        is_loss=close_result.get("is_loss")
                    )
                else:
                    logger.warning(
                        "position_close_failed_in_database",
                        service="backend",
                        position_id=position_id,
                        error=close_result.get("error")
                    )
            except Exception as persistence_error:
                # Log error but don't fail the entire handler
                log_error_with_context(
                    "position_close_persistence_failed",
                    error=persistence_error,
                    component="agent_event_subscriber",
                    position_id=position_id,
                    symbol=symbol
                )
            
            # Format position closed data for frontend
            position_data = {
                "position_id": position_id,
                "symbol": symbol,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "exit_reason": exit_reason,
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
            }
            
            # Broadcast via WebSocket
            await websocket_manager.broadcast(
                {"type": "position_closed", "data": position_data},
                channel="position_closed"
            )
            
            logger.debug(
                "agent_event_subscriber_position_closed_broadcast",
                service="backend",
                position_id=position_id,
                symbol=symbol,
                pnl=pnl
            )
            
            # Broadcast portfolio update after position closed
            await self._broadcast_portfolio_update()
            
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_position_closed_error",
                error=e,
                component="agent_event_subscriber"
            )
    
    async def _handle_model_prediction_complete(self, payload: Dict[str, Any]):
        """Handle ModelPredictionCompleteEvent.
        
        Args:
            payload: ModelPredictionCompleteEvent payload
        """
        # This event is already included in DecisionReadyEvent,
        # so we just log it for now
        try:
            symbol = payload.get("symbol", "")
            consensus_signal = payload.get("consensus_signal", 0.0)
            consensus_confidence = payload.get("consensus_confidence", 0.0)

            logger.debug(
                "agent_event_subscriber_model_prediction_complete",
                service="backend",
                symbol=symbol,
                consensus_signal=consensus_signal,
                consensus_confidence=consensus_confidence
            )

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_model_prediction_complete_error",
                error=e,
                component="agent_event_subscriber"
            )

    async def _handle_market_tick(self, payload: Dict[str, Any]):
        """Handle MarketTickEvent.
        
        Args:
            payload: MarketTickEvent payload
        """
        try:
            symbol = payload.get("symbol", "BTCUSD")
            price = payload.get("price", 0.0)
            volume = payload.get("volume", 0.0)
            timestamp = payload.get("timestamp")

            # Format ticker data for frontend
            ticker_data = {
                "symbol": symbol,
                "price": float(price),
                "volume": float(volume),
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
            }

            # Broadcast via WebSocket
            await websocket_manager.broadcast(
                {"type": "market_tick", "data": ticker_data},
                channel="market_data"
            )

            logger.debug(
                "agent_event_subscriber_market_tick_broadcast",
                service="backend",
                symbol=symbol,
                price=price
            )
            
            # Update position prices and broadcast portfolio update
            await self._update_position_prices(symbol, float(price))
            await self._broadcast_portfolio_update()

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_market_tick_error",
                error=e,
                component="agent_event_subscriber"
            )
    
    async def _update_position_prices(self, symbol: str, current_price: float):
        """Update current_price and unrealized_pnl for open positions matching symbol.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
        """
        try:
            from backend.core.database import AsyncSessionLocal, Position, PositionStatus, TradeSide
            
            async with AsyncSessionLocal() as session:
                # Get all open positions for this symbol
                from sqlalchemy import select
                query = select(Position).where(
                    Position.symbol == symbol,
                    Position.status == PositionStatus.OPEN
                )
                result = await session.execute(query)
                positions = result.scalars().all()
                
                if not positions:
                    return
                
                # Update each position
                for position in positions:
                    position.current_price = Decimal(str(current_price))
                    
                    # Calculate unrealized PnL
                    if position.side == TradeSide.BUY:
                        unrealized_pnl = (current_price - float(position.entry_price)) * float(position.quantity)
                    else:  # SELL
                        unrealized_pnl = (float(position.entry_price) - current_price) * float(position.quantity)
                    
                    position.unrealized_pnl = Decimal(str(unrealized_pnl))
                
                await session.commit()
                
                logger.debug(
                    "agent_event_subscriber_position_prices_updated",
                    service="backend",
                    symbol=symbol,
                    current_price=current_price,
                    positions_updated=len(positions)
                )
                
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_update_position_prices_error",
                error=e,
                component="agent_event_subscriber",
                symbol=symbol
            )
    
    async def _broadcast_portfolio_update(self):
        """Broadcast portfolio update via WebSocket."""
        try:
            from backend.core.database import AsyncSessionLocal
            from backend.services.portfolio_service import portfolio_service
            
            async with AsyncSessionLocal() as session:
                portfolio_summary = await portfolio_service.get_portfolio_summary(session)
                
                if portfolio_summary:
                    # Format portfolio data for frontend
                    portfolio_data = {
                        "total_value": float(portfolio_summary.get("total_value", 0)),
                        "available_balance": float(portfolio_summary.get("available_balance", 0)),
                        "open_positions": portfolio_summary.get("open_positions", 0),
                        "total_unrealized_pnl": float(portfolio_summary.get("total_unrealized_pnl", 0)),
                        "total_realized_pnl": float(portfolio_summary.get("total_realized_pnl", 0)),
                        "positions": portfolio_summary.get("positions", [])
                    }
                    
                    # Broadcast via WebSocket
                    await websocket_manager.broadcast(
                        {"type": "portfolio_update", "data": portfolio_data},
                        channel="portfolio"
                    )
                    
                    logger.debug(
                        "agent_event_subscriber_portfolio_update_broadcast",
                        service="backend",
                        total_value=portfolio_data["total_value"],
                        open_positions=portfolio_data["open_positions"]
                    )
                    
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_broadcast_portfolio_update_error",
                error=e,
                component="agent_event_subscriber"
            )


# Global subscriber instance
agent_event_subscriber = AgentEventSubscriber()
