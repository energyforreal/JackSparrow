"""
Agent Event Subscriber - Bridges Redis Streams to WebSocket.

Subscribes to agent events from Redis Streams and broadcasts them to
frontend clients via WebSocket.
"""

import json
import asyncio
import time
import random
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError, BusyLoadingError, ConnectionError, TimeoutError

from backend.core.redis import get_redis
from backend.api.websocket.unified_manager import unified_websocket_manager
from backend.core.logging import log_error_with_context
from backend.services.trade_persistence_service import trade_persistence_service
from backend.core.websocket_messages import (
    create_signal_update, create_portfolio_update, create_trade_update,
    create_market_update, create_agent_state_update, create_model_update
)
from decimal import Decimal

from backend.core.enums import SignalType

logger = structlog.get_logger()


def _v15_ws_fields_from_predictions(
    model_predictions: Any,
    reasoning_chain: Any,
) -> Dict[str, Any]:
    """Best-effort v15 fields for WebSocket signal payload (optional / backward compatible)."""
    out: Dict[str, Any] = {}
    preds = model_predictions
    if preds is None and isinstance(reasoning_chain, dict):
        preds = reasoning_chain.get("model_predictions")
    if not isinstance(preds, list):
        return out
    best: Optional[tuple] = None
    best_abs = -1.0
    for p in preds:
        if not isinstance(p, dict):
            continue
        ctx = p.get("context") or {}
        if not isinstance(ctx, dict) or ctx.get("format") != "v15_pipeline":
            continue
        try:
            edge = float(p.get("prediction", 0.0))
        except (TypeError, ValueError):
            edge = 0.0
        if abs(edge) >= best_abs:
            best_abs = abs(edge)
            best = (edge, ctx)
    if not best:
        return out
    edge, ctx = best
    out["edge"] = edge
    if ctx.get("p_buy") is not None:
        out["p_buy"] = ctx.get("p_buy")
    if ctx.get("p_sell") is not None:
        out["p_sell"] = ctx.get("p_sell")
    if ctx.get("p_hold") is not None:
        out["p_hold"] = ctx.get("p_hold")
    if ctx.get("timeframe") is not None:
        out["v15_timeframe"] = ctx.get("timeframe")
    return out


async def _append_v15_edge_history_redis(symbol: str, signal_data: Dict[str, Any]) -> None:
    if signal_data.get("edge") is None:
        return
    try:
        r = await get_redis(required=False)
        if not r:
            return
        key = f"jacksparrow:v15:edge_history:{symbol}"
        entry = json.dumps(
            {
                "ts": signal_data.get("timestamp"),
                "edge": signal_data["edge"],
                "signal": signal_data.get("signal"),
                "timeframe": signal_data.get("v15_timeframe"),
            },
            default=str,
        )
        await r.lpush(key, entry)
        await r.ltrim(key, 0, 199)
    except Exception:
        pass


def _model_consensus_row(
    model_name: str,
    signal_value: Any,
    pred_confidence: float,
    prediction_value: Any,
    pred: Dict[str, Any],
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "model_name": model_name,
        "signal": signal_value,
        "confidence": pred_confidence,
        "prediction": prediction_value,
    }
    pctx = pred.get("context") or {}
    if isinstance(pctx, dict) and pctx.get("format") == "v15_pipeline":
        if pctx.get("p_buy") is not None:
            row["p_buy"] = pctx.get("p_buy")
        if pctx.get("p_sell") is not None:
            row["p_sell"] = pctx.get("p_sell")
        if pctx.get("p_hold") is not None:
            row["p_hold"] = pctx.get("p_hold")
        if pctx.get("timeframe") is not None:
            row["timeframe"] = pctx.get("timeframe")
        row["edge"] = prediction_value
    return row


def _map_consensus_signal_to_string(value: Any) -> str:
    """Map numeric consensus_signal (-1 to +1) to discrete SignalType string.
    
    Frontend expects signal as string (STRONG_BUY, BUY, HOLD, etc.), not numeric.
    """
    if isinstance(value, str) and SignalType.is_valid(value):
        return value
    if not isinstance(value, (int, float)):
        return "HOLD"
    pred_value = float(value)
    if abs(pred_value) < 0.2:
        return "HOLD"
    if pred_value > 0.6:
        return "STRONG_BUY"
    if pred_value > 0.2:
        return "BUY"
    if pred_value < -0.6:
        return "STRONG_SELL"
    return "SELL"


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
        self._consume_retry_count: int = 0
        self._portfolio_update_lock = asyncio.Lock()  # Lock for portfolio updates to prevent race conditions
        self._processed_events: set = set()  # Track processed event IDs for deduplication

    def _next_retry_delay(self) -> float:
        """Exponential backoff with jitter for stream consume retries."""
        self._consume_retry_count += 1
        base = min(8.0, 0.5 * (2 ** min(self._consume_retry_count, 5)))
        return base + random.uniform(0.0, 0.4)

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
            redis_client = await get_redis()
            if redis_client is None:
                logger.warning(
                    "agent_event_subscriber_start_redis_unavailable",
                    service="backend",
                    message="Cannot start: Redis unavailable"
                )
                return
            self._redis_client = redis_client

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
                    self._redis_client = await get_redis()
                    if self._redis_client is None:
                        await asyncio.sleep(1)
                        continue
                    self._consume_retry_count = 0
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
                # Successful poll cycle - reset retry backoff.
                self._consume_retry_count = 0

            except asyncio.CancelledError:
                logger.info(
                    "agent_event_subscriber_consume_loop_cancelled",
                    service="backend"
                )
                raise
            except BusyLoadingError as e:
                delay = self._next_retry_delay()
                logger.warning(
                    "agent_event_subscriber_redis_busy_loading",
                    service="backend",
                    stream=self.stream_name,
                    retry_delay_s=round(delay, 2),
                    error=str(e),
                    message="Redis is loading dataset in memory; waiting before retry",
                )
                await asyncio.sleep(delay)
            except (ConnectionError, TimeoutError) as e:
                delay = self._next_retry_delay()
                logger.warning(
                    "agent_event_subscriber_redis_connection_retry",
                    service="backend",
                    stream=self.stream_name,
                    retry_delay_s=round(delay, 2),
                    error=str(e),
                    message="Redis connection issue while consuming stream; reconnecting",
                )
                self._redis_client = await get_redis()
                await asyncio.sleep(delay)
            except Exception as e:
                delay = self._next_retry_delay()
                log_error_with_context(
                    "agent_event_subscriber_consume_loop_error",
                    error=e,
                    component="agent_event_subscriber",
                    stream=self.stream_name
                )
                await asyncio.sleep(delay)

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
            await self._handle_event(event_type, payload, event_dict)

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

    async def _handle_event(self, event_type: str, payload: Dict[str, Any], event_dict: Optional[Dict[str, Any]] = None):
        """Handle different event types with deduplication.
        
        Args:
            event_type: Type of event
            payload: Event payload
            event_dict: Full event dictionary (event_id/correlation_id at top level, not in payload)
        """
        # Extract event ID for deduplication - agent places event_id at top level, not in payload
        event_dict = event_dict or {}
        event_id = (
            event_dict.get("event_id")
            or event_dict.get("correlation_id")
            or payload.get("event_id")
            or payload.get("correlation_id")
        )
        
        # Check if event was already processed (deduplication)
        if event_id:
            # Use Redis SET to track processed events with TTL (5 minutes)
            redis = await get_redis()
            if redis:
                try:
                    # Check if event ID exists in processed events set
                    key = f"processed_event:{event_id}"
                    exists = await redis.exists(key)
                    if exists:
                        logger.debug(
                            "agent_event_subscriber_duplicate_event_skipped",
                            service="backend",
                            event_id=event_id,
                            event_type=event_type,
                            message="Event already processed, skipping duplicate"
                        )
                        return
                    
                    # Mark event as processed with 5 minute TTL
                    await redis.setex(key, 300, "1")
                except Exception as e:
                    # If Redis check fails, log but continue processing
                    logger.warning(
                        "agent_event_subscriber_dedup_check_failed",
                        service="backend",
                        event_id=event_id,
                        error=str(e),
                        message="Continuing with event processing despite deduplication check failure"
                    )
        
        try:
            # Log event processing for debugging
            logger.debug(
                "agent_event_subscriber_processing_event",
                service="backend",
                event_type=event_type,
                event_id=event_id or 'unknown',
                payload_keys=list(payload.keys()) if isinstance(payload, dict) else 'non-dict'
            )

            # Consolidated event routing - reduced from 8 handlers to 3 core handlers
            if event_type in ["decision_ready", "order_fill", "position_closed"]:
                await self._handle_trading_event(event_type, payload)
            elif event_type == "state_transition":
                await self._handle_system_event(event_type, payload)
            elif event_type in ["model_prediction_complete", "reasoning_complete", "market_tick"]:
                await self._handle_data_event(event_type, payload)
            else:
                # Some low-level events are expected but intentionally ignored by the backend bridge.
                # Log them at debug level to avoid noisy warnings while retaining observability.
                known_ignored_events = {
                    "candle_closed",
                    "feature_request",
                    "feature_computed",
                    "model_prediction_request",
                    "model_prediction",
                    "reasoning_request",
                    "price_fluctuation",
                }
                if event_type in known_ignored_events:
                    logger.debug(
                        "agent_event_subscriber_ignored_event_type",
                        service="backend",
                        event_type=event_type,
                        event_id=event_id or 'unknown',
                        message="Ignoring low-level agent event type"
                    )
                else:
                    logger.warning(
                        "agent_event_subscriber_unknown_event_type",
                        service="backend",
                        event_type=event_type,
                        event_id=event_id or 'unknown',
                        message="Received unknown event type, ignoring"
                    )
            # Add more event handlers as needed

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_handle_event_error",
                error=e,
                component="agent_event_subscriber",
                event_type=event_type,
                event_id=event_id
            )

    # Consolidated Event Handlers - Reduced from 8 individual handlers to 3

    async def _handle_order_fill(self, payload: Dict[str, Any]):
        """Handle OrderFillEvent - persist to DB and broadcast to frontend.
        
        Args:
            payload: OrderFillEvent payload (order_id, trade_id, symbol, side, quantity, fill_price, timestamp)
        """
        try:
            order_id = payload.get("order_id", "")
            trade_id = payload.get("trade_id", "")
            symbol = payload.get("symbol", "")
            side = payload.get("side", "")
            quantity = payload.get("quantity", 0.0)
            fill_price = payload.get("fill_price", 0.0)
            timestamp = payload.get("timestamp")
            
            logger.info(
                "agent_event_subscriber_order_fill_received",
                service="backend",
                order_id=order_id,
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                fill_price=fill_price,
                message="AgentEventSubscriber received OrderFillEvent - starting persistence"
            )
            
            # Validate inputs
            if not trade_id:
                logger.error(
                    "agent_event_subscriber_missing_trade_id",
                    order_id=order_id,
                    symbol=symbol,
                    message="Trade ID is missing - cannot persist trade"
                )
                return
            
            if not symbol:
                logger.error(
                    "agent_event_subscriber_missing_symbol",
                    order_id=order_id,
                    trade_id=trade_id,
                    message="Symbol is missing - cannot persist trade"
                )
                return
            
            if quantity <= 0:
                logger.error(
                    "agent_event_subscriber_invalid_quantity",
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=symbol,
                    quantity=quantity,
                    message="Quantity is zero or negative - cannot persist trade"
                )
                return
            
            if fill_price <= 0:
                logger.error(
                    "agent_event_subscriber_invalid_fill_price",
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=symbol,
                    fill_price=fill_price,
                    message="Fill price is zero or negative - cannot persist trade"
                )
                return
            
            # Convert timestamp to datetime if it's a string
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except Exception:
                    timestamp = datetime.utcnow()
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.utcnow()

            # Initialize position_id variable for use after try block
            position_id = None
            
            # Persist trade and position to database
            try:
                logger.info(
                    "agent_event_subscriber_persisting_trade",
                    service="backend",
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price,
                    message="Calling trade_persistence_service.create_trade_and_position"
                )
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
                
                position_id = persistence_result.get("position_id")

                if not position_id:
                    # Duplicate trade_id: create_trade_and_position skips creation and returns position_id None
                    logger.warning(
                        "agent_event_subscriber_position_not_created",
                        service="backend",
                        trade_id=trade_id,
                        symbol=symbol,
                        persistence_result=persistence_result,
                        message="Position ID missing (trade may already exist from duplicate event or prior run)"
                    )
                else:
                    logger.info(
                        "trade_persisted_to_database",
                        service="backend",
                        trade_id=trade_id,
                        position_id=position_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        fill_price=fill_price,
                        message="Trade and position successfully persisted to database"
                    )
                    
                    # Invalidate portfolio cache immediately to ensure fresh data
                    from backend.services.portfolio_service import portfolio_service
                    await portfolio_service.invalidate_portfolio_cache()
                    logger.debug(
                        "portfolio_cache_invalidated_after_position_creation",
                        trade_id=trade_id,
                        position_id=position_id
                    )
            except Exception as persistence_error:
                # Log error but don't fail the entire handler
                log_error_with_context(
                    "trade_persistence_failed",
                    error=persistence_error,
                    component="agent_event_subscriber",
                    trade_id=trade_id,
                    symbol=symbol,
                    order_id=order_id,
                    quantity=quantity,
                    fill_price=fill_price,
                    message="Failed to persist trade and position to database"
                )

            # Format trade data for frontend - include position_id if available
            ts_str = timestamp.isoformat() if isinstance(timestamp, datetime) else (timestamp or datetime.now(timezone.utc).isoformat())
            trade_data = {
                "order_id": order_id,
                "trade_id": trade_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": fill_price,
                "status": "EXECUTED",
                "executed_at": ts_str,
                "timestamp": ts_str,
            }
            
            # Add position_id if position was created successfully
            if position_id:
                trade_data["position_id"] = position_id
                logger.debug(
                    "trade_executed_with_position_id",
                    service="backend",
                    trade_id=trade_id,
                    position_id=position_id,
                    message="Including position_id in trade_executed message"
                )
            else:
                logger.warning(
                    "trade_executed_without_position_id",
                    service="backend",
                    trade_id=trade_id,
                    symbol=symbol,
                    message="Position ID not available - position may not have been created"
                )

            # Broadcast via WebSocket using simplified message format
            trade_message = create_trade_update(trade_data)
            await unified_websocket_manager.broadcast(trade_message, channel="data_update")

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
            side = payload.get("side", "")
            entry_price = payload.get("entry_price", 0.0)
            exit_price = payload.get("exit_price", 0.0)
            quantity = payload.get("quantity", 0.0)
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
                    closed_at=timestamp,
                    symbol=symbol or None,
                    side=side or None,
                    entry_price=float(entry_price) if entry_price else None,
                    quantity=float(quantity) if quantity else None,
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
                    
                    # Invalidate portfolio cache immediately to ensure fresh data
                    from backend.services.portfolio_service import portfolio_service
                    await portfolio_service.invalidate_portfolio_cache()
                    logger.debug(
                        "portfolio_cache_invalidated_after_position_closed",
                        position_id=position_id
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
            
            # Only broadcast full portfolio update - avoid partial update that would
            # briefly replace portfolio with {position_closed: {...}} on frontend
            await self._broadcast_portfolio_update()
            
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_position_closed_error",
                error=e,
                component="agent_event_subscriber"
            )
    
    async def _handle_model_prediction_complete(self, payload: Dict[str, Any]):
        """Handle ModelPredictionCompleteEvent - broadcast to frontend.
        
        Args:
            payload: ModelPredictionCompleteEvent payload
        """
        try:
            symbol = payload.get("symbol", "")
            predictions = payload.get("predictions", [])
            consensus_signal = payload.get("consensus_signal", 0.0)
            consensus_confidence = payload.get("consensus_confidence", 0.0)
            timestamp = payload.get("timestamp")
            
            # Extract individual model reasoning from predictions
            individual_reasoning = []
            model_consensus = []
            
            if isinstance(predictions, list):
                for pred in predictions:
                    if isinstance(pred, dict):
                        model_name = pred.get("model_name", "Unknown")
                        reasoning = pred.get("reasoning", "")
                        pred_confidence = pred.get("confidence", 0.0)
                        prediction_value = pred.get("prediction", 0.0)
                        signal_value = pred.get("signal", "HOLD")
                        
                        # Normalize to 0-1 range for frontend schema consistency
                        if pred_confidence > 1.0:
                            pred_confidence = pred_confidence / 100.0
                        pred_confidence = max(0.0, min(1.0, pred_confidence))
                        
                        individual_reasoning.append({
                            "model_name": model_name,
                            "reasoning": reasoning,
                            "confidence": pred_confidence,
                            "prediction": prediction_value
                        })
                        
                        # Build model consensus entry
                        model_consensus.append(
                            _model_consensus_row(
                                model_name,
                                signal_value,
                                pred_confidence,
                                prediction_value,
                                pred,
                            )
                        )
            
            # Handle timestamp formatting - ensure 'Z' suffix for UTC
            from backend.services.time_service import time_service
            formatted_timestamp = None
            if timestamp:
                if isinstance(timestamp, datetime):
                    # Ensure UTC and add 'Z' suffix
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    formatted_timestamp = timestamp.isoformat().replace('+00:00', 'Z')
                    if not formatted_timestamp.endswith('Z'):
                        formatted_timestamp += 'Z'
                elif isinstance(timestamp, str):
                    # Ensure 'Z' suffix if not present
                    if not (timestamp.endswith('Z') or '+' in timestamp[-6:] or '-' in timestamp[-6:]):
                        formatted_timestamp = timestamp + 'Z'
                    else:
                        formatted_timestamp = timestamp
                else:
                    formatted_timestamp = time_service.get_time_info()["server_time"]
            else:
                formatted_timestamp = time_service.get_time_info()["server_time"]
            
            # Normalize consensus confidence to 0.0-1.0 range (NOT 0-100)
            # Frontend will handle conversion to percentage for display
            if consensus_confidence > 1.0:
                consensus_confidence = consensus_confidence / 100.0
            consensus_confidence = max(0.0, min(1.0, consensus_confidence))
            
            # Map numeric consensus_signal to discrete string for frontend Signal type
            signal_str = _map_consensus_signal_to_string(consensus_signal)
            
            # Broadcast model prediction update using simplified message format
            model_data = {
                "symbol": symbol,
                "consensus_signal": signal_str,
                "signal": signal_str,
                "consensus_confidence": consensus_confidence,
                "individual_model_reasoning": individual_reasoning,
                "model_consensus": model_consensus,
                "model_predictions": predictions,
                "timestamp": formatted_timestamp
            }
            model_message = create_model_update(model_data)
            await unified_websocket_manager.broadcast(model_message, channel="data_update")

            logger.info(
                "agent_event_subscriber_model_prediction_complete_broadcast",
                service="backend",
                symbol=symbol,
                consensus_signal=consensus_signal,
                consensus_confidence=consensus_confidence,
                prediction_count=len(predictions)
            )

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_model_prediction_complete_error",
                error=e,
                component="agent_event_subscriber"
            )

    async def _handle_reasoning_complete(self, payload: Dict[str, Any]):
        """Handle ReasoningCompleteEvent.
        
        Args:
            payload: ReasoningCompleteEvent payload
        """
        try:
            reasoning_chain = payload.get("reasoning_chain", {})
            symbol = payload.get("symbol", "BTCUSD")
            final_confidence = payload.get("final_confidence", 0.0)
            timestamp = payload.get("timestamp")
            
            # Extract reasoning chain steps
            reasoning_steps = reasoning_chain.get("steps", []) if isinstance(reasoning_chain, dict) else []
            conclusion = reasoning_chain.get("conclusion", "") if isinstance(reasoning_chain, dict) else ""
            chain_id = reasoning_chain.get("chain_id", "") if isinstance(reasoning_chain, dict) else ""
            market_context = reasoning_chain.get("market_context", {}) if isinstance(reasoning_chain, dict) else {}
            
            # Normalize final confidence to 0.0-1.0 range (NOT 0-100)
            # Frontend will handle conversion to percentage for display
            if final_confidence > 1.0:
                final_confidence = final_confidence / 100.0
            final_confidence = max(0.0, min(1.0, final_confidence))
            
            # Handle timestamp formatting - ensure 'Z' suffix for UTC
            from backend.services.time_service import time_service
            formatted_timestamp = None
            if timestamp:
                if isinstance(timestamp, datetime):
                    # Ensure UTC and add 'Z' suffix
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    formatted_timestamp = timestamp.isoformat().replace('+00:00', 'Z')
                    if not formatted_timestamp.endswith('Z'):
                        formatted_timestamp += 'Z'
                elif isinstance(timestamp, str):
                    # Ensure 'Z' suffix if not present
                    if not (timestamp.endswith('Z') or '+' in timestamp[-6:] or '-' in timestamp[-6:]):
                        formatted_timestamp = timestamp + 'Z'
                    else:
                        formatted_timestamp = timestamp
                else:
                    formatted_timestamp = time_service.get_time_info()["server_time"]
            else:
                formatted_timestamp = time_service.get_time_info()["server_time"]
            
            # Broadcast reasoning chain update using simplified format
            reasoning_data = {
                "symbol": symbol,
                "reasoning_chain": reasoning_steps,
                "conclusion": conclusion,
                "final_confidence": final_confidence,
                "chain_id": chain_id,
                "market_context": market_context,
                "timestamp": formatted_timestamp
            }
            # Reasoning is part of signal data, so use signal update
            signal_message = create_signal_update(reasoning_data)
            await unified_websocket_manager.broadcast(signal_message, channel="data_update")

            logger.info(
                "agent_event_subscriber_reasoning_complete_broadcast",
                service="backend",
                symbol=symbol,
                chain_id=chain_id,
                final_confidence=final_confidence,
                step_count=len(reasoning_steps)
            )

        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_reasoning_complete_error",
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

            # Format ticker data for frontend with all available market data
            ticker_data = {
                "symbol": symbol,
                "price": float(price),
                "volume": float(volume),
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
                # Include 24h statistics if available
                "change_24h_pct": payload.get("change_24h_pct"),
                "change_24h": payload.get("change_24h"),
                "high_24h": payload.get("high_24h"),
                "low_24h": payload.get("low_24h"),
                # Additional market data
                "turnover_usd": payload.get("turnover_usd"),
                "oi": payload.get("oi"),
                "spot_price": payload.get("spot_price"),
                "mark_price": payload.get("mark_price"),
                "bid_price": payload.get("bid_price"),
                "ask_price": payload.get("ask_price"),
                "bid_size": payload.get("bid_size"),
                "ask_size": payload.get("ask_size"),
            }

            # Broadcast via WebSocket using simplified message format
            market_message = create_market_update(ticker_data)
            await unified_websocket_manager.broadcast(market_message, channel="data_update")

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
        
        Uses database transaction to ensure atomicity - all positions updated or none.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
        """
        try:
            from backend.core.database import AsyncSessionLocal, Position, PositionStatus, TradeSide
            
            async with AsyncSessionLocal() as session:
                try:
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
                    
                    # Update each position within transaction
                    for position in positions:
                        position.current_price = Decimal(str(current_price))
                        
                        # Calculate unrealized PnL
                        if position.side == TradeSide.BUY:
                            unrealized_pnl = (current_price - float(position.entry_price)) * float(position.quantity)
                        else:  # SELL
                            unrealized_pnl = (float(position.entry_price) - current_price) * float(position.quantity)
                        
                        position.unrealized_pnl = Decimal(str(unrealized_pnl))
                    
                    # Commit all updates atomically
                    await session.commit()
                    
                    logger.debug(
                        "agent_event_subscriber_position_prices_updated",
                        service="backend",
                        symbol=symbol,
                        current_price=current_price,
                        positions_updated=len(positions)
                    )
                    
                except Exception as e:
                    # Rollback on any error to maintain consistency
                    await session.rollback()
                    raise
                
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_update_position_prices_error",
                error=e,
                component="agent_event_subscriber",
                symbol=symbol
            )
    
    async def _broadcast_portfolio_update(self):
        """Broadcast portfolio update via WebSocket.
        
        Uses async lock to prevent race conditions when multiple events trigger updates.
        Uses shared serialization function to ensure identical format with API responses.
        """
        # Use lock to prevent concurrent portfolio updates
        async with self._portfolio_update_lock:
            try:
                from backend.core.database import AsyncSessionLocal
                from backend.services.portfolio_service import portfolio_service
                
                async with AsyncSessionLocal() as session:
                    # Get portfolio summary (may be cached)
                    portfolio_summary = await portfolio_service.get_portfolio_summary(session)
                    
                    if portfolio_summary:
                        try:
                            # Use shared serialization function to ensure identical format with API
                            portfolio_data = portfolio_service.serialize_portfolio_summary(portfolio_summary)
                            
                            # Validate portfolio data structure before broadcasting
                            if not portfolio_data or "total_value" not in portfolio_data:
                                logger.error(
                                    "portfolio_data_validation_failed",
                                    service="backend",
                                    message="Portfolio data missing required fields after serialization"
                                )
                                return
                            
                            # Broadcast via WebSocket using simplified format
                            portfolio_message = create_portfolio_update(portfolio_data)
                            await unified_websocket_manager.broadcast(portfolio_message, channel="data_update")
                            
                            logger.debug(
                                "agent_event_subscriber_portfolio_update_broadcast",
                                service="backend",
                                total_value=portfolio_data["total_value"],
                                open_positions=portfolio_data["open_positions"],
                                positions_count=len(portfolio_data.get("positions", [])),
                                timestamp=portfolio_data.get("timestamp"),
                                data_source="websocket"
                            )
                        except ValueError as e:
                            # Log validation error but don't fail - return empty data
                            logger.error(
                                "portfolio_serialization_validation_failed",
                                error=str(e),
                                message="Portfolio data validation failed, skipping broadcast"
                            )
                        except Exception as e:
                            logger.error(
                                "portfolio_serialization_error",
                                error=str(e),
                                message="Error serializing portfolio data"
                            )
                        
            except Exception as e:
                log_error_with_context(
                    "agent_event_subscriber_broadcast_portfolio_update_error",
                    error=e,
                    component="agent_event_subscriber"
                )

    # Consolidated Event Handlers - Reduced from 8 individual handlers to 3

    async def _handle_trading_event(self, event_type: str, payload: Dict[str, Any]):
        """Consolidated handler for all trading-related events.

        Handles: decision_ready, order_fill, position_closed
        """
        try:
            if event_type == "decision_ready":
                await self._handle_decision_ready_consolidated(payload)
            elif event_type == "order_fill":
                await self._handle_order_fill(payload)
            elif event_type == "position_closed":
                await self._handle_position_closed(payload)
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_trading_event_error",
                error=e,
                component="agent_event_subscriber",
                event_type=event_type
            )

    async def _handle_system_event(self, event_type: str, payload: Dict[str, Any]):
        """Consolidated handler for system-related events.

        Handles: state_transition
        """
        try:
            if event_type == "state_transition":
                await self._handle_state_transition_consolidated(payload)
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_system_event_error",
                error=e,
                component="agent_event_subscriber",
                event_type=event_type
            )

    async def _handle_data_event(self, event_type: str, payload: Dict[str, Any]):
        """Consolidated handler for data-related events.

        Handles: model_prediction_complete, reasoning_complete, market_tick
        """
        try:
            if event_type == "model_prediction_complete":
                await self._handle_model_prediction_consolidated(payload)
            elif event_type == "reasoning_complete":
                await self._handle_reasoning_complete_consolidated(payload)
            elif event_type == "market_tick":
                await self._handle_market_tick_consolidated(payload)
        except Exception as e:
            log_error_with_context(
                "agent_event_subscriber_data_event_error",
                error=e,
                component="agent_event_subscriber",
                event_type=event_type
            )

    # Individual handler implementations (consolidated logic)

    async def _handle_decision_ready_consolidated(self, payload: Dict[str, Any]):
        """Handle decision_ready events with simplified logic."""
        signal = payload.get("signal", "HOLD")
        confidence = payload.get("confidence", 0.0)
        symbol = payload.get("symbol", "BTCUSD")
        reasoning_chain = payload.get("reasoning_chain", {})

        # Normalize confidence to 0.0-1.0 range
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))

        # Extract reasoning data
        reasoning_steps = reasoning_chain.get("steps", []) if isinstance(reasoning_chain, dict) else []
        conclusion = reasoning_chain.get("conclusion", "") if isinstance(reasoning_chain, dict) else ""
        market_context = reasoning_chain.get("market_context", {}) if isinstance(reasoning_chain, dict) else {}

        # Optionally enrich signal with per-model consensus when available in reasoning payload
        individual_reasoning = []
        model_consensus = []

        try:
            model_predictions = None

            # Prefer explicit model_predictions from reasoning_chain payload
            if isinstance(reasoning_chain, dict):
                model_predictions = reasoning_chain.get("model_predictions")

            # Fallback: look in embedded market_context if present
            if model_predictions is None and isinstance(market_context, dict):
                model_predictions = market_context.get("model_predictions")

            if isinstance(model_predictions, list):
                for pred in model_predictions:
                    if isinstance(pred, dict):
                        model_name = pred.get("model_name", "Unknown")
                        reasoning = pred.get("reasoning", "")
                        pred_confidence = pred.get("confidence", 0.0)
                        prediction_value = pred.get("prediction", 0.0)
                        signal_value = pred.get("signal", "HOLD")

                        # Normalize to 0-1 range for frontend schema consistency
                        if pred_confidence > 1.0:
                            pred_confidence = pred_confidence / 100.0
                        pred_confidence = max(0.0, min(1.0, pred_confidence))

                        individual_reasoning.append({
                            "model_name": model_name,
                            "reasoning": reasoning,
                            "confidence": pred_confidence,
                            "prediction": prediction_value
                        })

                        model_consensus.append(
                            _model_consensus_row(
                                model_name,
                                signal_value,
                                pred_confidence,
                                prediction_value,
                                pred,
                            )
                        )
        except Exception:
            # Per-model enrichment is best-effort only; never break decision broadcasts.
            individual_reasoning = []
            model_consensus = []

        # If payload confidence is 0 but we have model consensus with non-zero confidences,
        # use average of model confidences so UI never shows 0% when we have real data
        if confidence < 0.01 and model_consensus:
            model_confs = [c.get("confidence", 0) for c in model_consensus]
            model_confs_01 = [c / 100.0 if c > 1.0 else c for c in model_confs]
            avg_model = sum(model_confs_01) / len(model_confs_01) if model_confs_01 else 0.0
            if avg_model > 0:
                confidence = max(0.0, min(1.0, avg_model))

        # Create signal data for WebSocket
        signal_data = {
            "signal": signal,
            "confidence": confidence,
            "symbol": symbol,
            "reasoning_chain": reasoning_steps,
            "conclusion": conclusion,
            "individual_model_reasoning": individual_reasoning,
            "model_consensus": model_consensus,
            "timestamp": payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        }
        signal_data.update(
            _v15_ws_fields_from_predictions(model_predictions, reasoning_chain)
        )

        await _append_v15_edge_history_redis(symbol, signal_data)

        # Broadcast signal update
        signal_message = create_signal_update(signal_data)
        await unified_websocket_manager.broadcast(signal_message, channel="data_update")

    async def _handle_order_fill_consolidated(self, payload: Dict[str, Any]):
        """Handle order_fill events with simplified logic (fallback; prefer _handle_order_fill for persistence)."""
        trade_id = payload.get("trade_id", "")
        symbol = payload.get("symbol", "")
        quantity = payload.get("quantity", 0)
        price = payload.get("fill_price") or payload.get("price", 0)
        side = payload.get("side", "")

        # Create trade data (include executed_at and status for frontend)
        ts = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        trade_data = {
            "trade_id": trade_id,
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "side": side,
            "status": "EXECUTED",
            "executed_at": ts,
            "timestamp": ts,
        }

        # Broadcast trade update
        trade_message = create_trade_update(trade_data)
        await unified_websocket_manager.broadcast(trade_message, channel="data_update")

        # Update portfolio after trade
        await self._broadcast_portfolio_update()

    async def _handle_position_closed_consolidated(self, payload: Dict[str, Any]):
        """Handle position_closed events with simplified logic."""
        # Only broadcast full portfolio update - avoid partial update that would
        # briefly replace portfolio with {position_closed: {...}} on frontend
        await self._broadcast_portfolio_update()

    async def _handle_state_transition_consolidated(self, payload: Dict[str, Any]):
        """Handle state_transition events with simplified logic."""
        # StateTransitionEvent payload uses 'to_state' for the new state.
        # Fall back to 'state' for compatibility with any legacy publishers.
        state = payload.get("to_state") or payload.get("state", "UNKNOWN")
        reason = payload.get("reason", "")

        # Create agent state data
        state_data = {
            "state": state,
            "reason": reason,
            "timestamp": payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        }

        # Broadcast agent state update
        state_message = create_agent_state_update(state_data)
        await unified_websocket_manager.broadcast(state_message, channel="agent_update")

    async def _handle_model_prediction_consolidated(self, payload: Dict[str, Any]):
        """Handle model_prediction_complete events with simplified logic."""
        symbol = payload.get("symbol", "BTCUSD")
        predictions = payload.get("predictions", [])
        consensus_signal = payload.get("consensus_signal")
        consensus_confidence = payload.get("consensus_confidence", 0.0)

        # Normalize confidence
        if consensus_confidence > 1.0:
            consensus_confidence = consensus_confidence / 100.0

        # Map numeric consensus_signal to discrete string for frontend Signal type
        signal_str = _map_consensus_signal_to_string(payload.get("consensus_signal"))

        # Build per-model consensus and reasoning structures for frontend display
        individual_reasoning = []
        model_consensus = []

        if isinstance(predictions, list):
            for pred in predictions:
                if isinstance(pred, dict):
                    model_name = pred.get("model_name", "Unknown")
                    reasoning = pred.get("reasoning", "")
                    pred_confidence = pred.get("confidence", 0.0)
                    prediction_value = pred.get("prediction", 0.0)
                    signal_value = pred.get("signal", "HOLD")

                    # Normalize to 0-1 range for frontend schema consistency
                    if pred_confidence > 1.0:
                        pred_confidence = pred_confidence / 100.0
                    pred_confidence = max(0.0, min(1.0, pred_confidence))

                    individual_reasoning.append({
                        "model_name": model_name,
                        "reasoning": reasoning,
                        "confidence": pred_confidence,
                        "prediction": prediction_value
                    })

                    model_consensus.append(
                        _model_consensus_row(
                            model_name,
                            signal_value,
                            pred_confidence,
                            prediction_value,
                            pred,
                        )
                    )

        # Create model data
        model_data = {
            "symbol": symbol,
            "consensus_signal": signal_str,
            "signal": signal_str,
            "consensus_confidence": consensus_confidence,
            # Expose consensus confidence under the generic 'confidence' key
            # so frontend signal components can consume it consistently.
            "confidence": consensus_confidence,
            "model_predictions": predictions,
            "individual_model_reasoning": individual_reasoning,
            "model_consensus": model_consensus,
            "timestamp": payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        }

        # Broadcast model update
        model_message = create_model_update(model_data)
        await unified_websocket_manager.broadcast(model_message, channel="data_update")

    async def _handle_reasoning_complete_consolidated(self, payload: Dict[str, Any]):
        """Handle reasoning_complete events with simplified logic."""
        symbol = payload.get("symbol", "BTCUSD")
        reasoning_chain = payload.get("reasoning_chain", {})
        final_confidence = payload.get("final_confidence", 0.0)

        # Normalize confidence
        if final_confidence > 1.0:
            final_confidence = final_confidence / 100.0

        # Extract reasoning data
        steps = reasoning_chain.get("steps", []) if isinstance(reasoning_chain, dict) else []
        conclusion = reasoning_chain.get("conclusion", "") if isinstance(reasoning_chain, dict) else ""

        # Create reasoning data
        reasoning_data = {
            "symbol": symbol,
            "reasoning_chain": steps,
            "conclusion": conclusion,
            "final_confidence": final_confidence,
            # Expose final confidence under generic 'confidence' key so the
            # primary signal display always has a value to show.
            "confidence": final_confidence,
            "timestamp": payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        }

        # Broadcast reasoning update (part of signal data)
        signal_message = create_signal_update(reasoning_data)
        await unified_websocket_manager.broadcast(signal_message, channel="data_update")

    async def _handle_market_tick_consolidated(self, payload: Dict[str, Any]):
        """Handle market_tick events with simplified logic."""
        symbol = payload.get("symbol", "")
        price = payload.get("price", 0)
        volume = payload.get("volume")
        change_24h_pct = payload.get("change_24h_pct")

        # Create market data
        market_data = {
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "change_24h_pct": change_24h_pct,
            "timestamp": payload.get("timestamp", datetime.now(timezone.utc).isoformat())
        }

        # Broadcast market update
        market_message = create_market_update(market_data)
        await unified_websocket_manager.broadcast(market_message, channel="data_update")

        # Update portfolio prices
        await self._update_position_prices(symbol, float(price))


# Global subscriber instance
agent_event_subscriber = AgentEventSubscriber()
