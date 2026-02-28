"""
Event bus for trading agent.

Provides event-driven communication using Redis Streams.
"""

import json
import asyncio
from typing import Dict, Callable, List, Optional, Any
from datetime import datetime
import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError, ConnectionError

from agent.core.logging_utils import log_error_with_context
from agent.core.redis_config import get_redis
from agent.events.schemas import BaseEvent, EventType
from agent.events.utils import serialize_event, deserialize_event

logger = structlog.get_logger()


class EventBus:
    """Event bus using Redis Streams."""
    
    def __init__(self, stream_name: str = "trading_agent_events", consumer_group: str = "agent_consumers"):
        """Initialize event bus.
        
        Args:
            stream_name: Redis stream name
            consumer_group: Consumer group name for parallel processing
        """
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = f"consumer_{id(self)}"
        self.handlers: Dict[EventType, List[Callable]] = {}
        self.running = False
        self._consuming_task: Optional[asyncio.Task] = None
        self._dead_letter_stream = f"{stream_name}:dlq"
        self._max_retries = 3
        self._processing_lock: Dict[str, asyncio.Lock] = {}
    
    async def initialize(self):
        """Initialize event bus and create consumer group."""
        redis = await get_redis()
        
        if redis is None:
            logger.warning(
                "event_bus_initialization_skipped",
                stream=self.stream_name,
                message="Redis unavailable - event bus will not function"
            )
            return
        
        try:
            # Create consumer group if it doesn't exist
            await redis.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id="0",
                mkstream=True
            )
        except ResponseError as e:
            # Check for specific BUSYGROUP error code (Redis returns this when group already exists)
            error_str = str(e).upper()
            if "BUSYGROUP" in error_str:
                logger.debug(
                    "event_bus_consumer_group_exists",
                    stream=self.stream_name,
                    group=self.consumer_group,
                    message="Consumer group already exists, continuing"
                )
            else:
                # Other ResponseError - log as warning but don't fail
                logger.warning(
                    "event_bus_consumer_group_response_error",
                    stream=self.stream_name,
                    group=self.consumer_group,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
        except ConnectionError as e:
            # Redis connection error - this is a real problem
            log_error_with_context(
                "event_bus_consumer_group_connection_error",
                error=e,
                component="event_bus",
                stream=self.stream_name,
                group=self.consumer_group
            )
            raise  # Re-raise connection errors as they indicate a real problem
        except Exception as e:
            # Catch any other unexpected exceptions
            log_error_with_context(
                "event_bus_consumer_group_unexpected_error",
                error=e,
                component="event_bus",
                stream=self.stream_name,
                group=self.consumer_group
            )
            # Don't re-raise - allow event bus to continue, but log the error
        
        # Create dead letter queue consumer group
        try:
            await redis.xgroup_create(
                name=self._dead_letter_stream,
                groupname=self.consumer_group,
                id="0",
                mkstream=True
            )
        except Exception:
            pass
        
        logger.info(
            "event_bus_initialized",
            stream=self.stream_name,
            consumer_group=self.consumer_group,
            consumer_name=self.consumer_name
        )
    
    async def shutdown(self):
        """Shutdown event bus."""
        self.running = False
        
        if self._consuming_task:
            self._consuming_task.cancel()
            try:
                await self._consuming_task
            except asyncio.CancelledError:
                pass
        
        logger.info("event_bus_shutdown", stream=self.stream_name)
    
    async def publish(self, event: BaseEvent) -> bool:
        """Publish event to stream.
        
        Args:
            event: Event to publish
            
        Returns:
            True if published successfully
        """
        # EVENT BUS: Validate event is not None
        if event is None:
            logger.warning("EVENT BUS: Skipping publish — event is None")
            return False
        
        try:
            redis = await get_redis()
            
            if redis is None:
                logger.warning(
                    "event_publish_skipped",
                    event_id=event.event_id,
                    event_type=event.event_type,
                    message="Redis unavailable - event not published"
                )
                return False
            
            # Validate event before publishing
            if not event.event_type:
                logger.error(
                    "event_publish_validation_failed",
                    event_id=event.event_id,
                    reason="Missing event_type"
                )
                return False
            
            if not event.source:
                logger.error(
                    "event_publish_validation_failed",
                    event_id=event.event_id,
                    event_type=event.event_type,
                    reason="Missing source"
                )
                return False
            
            # Serialize event
            try:
                # Use model_dump() for Pydantic v2, fallback to dict() for v1
                if hasattr(event, 'model_dump'):
                    event_data = event.model_dump()
                else:
                    event_data = event.dict()
                event_data["_event_class"] = event.__class__.__name__
                
                # Validate serialized data
                if not event_data or not isinstance(event_data, dict):
                    logger.error(
                        "event_publish_validation_failed",
                        event_id=event.event_id,
                        event_type=event.event_type,
                        reason="Event serialization produced invalid data"
                    )
                    return False
                
                # Ensure required fields are present
                if "event_type" not in event_data or "source" not in event_data:
                    logger.error(
                        "event_publish_validation_failed",
                        event_id=event.event_id,
                        event_type=event.event_type,
                        reason="Missing required fields after serialization"
                    )
                    return False
                
            except Exception as e:
                log_error_with_context(
                    "event_publish_serialization_failed",
                    error=e,
                    component="event_bus",
                    correlation_id=event.event_id,
                    event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
                )
                return False
            
            # Publish to Redis Stream
            event_json_str = json.dumps(event_data, default=str)
            logger.debug(
                "event_publishing",
                event_id=event.event_id,
                event_type=event.event_type,
                event_data_keys=list(event_data.keys()),
                event_json_length=len(event_json_str),
                event_json_preview=event_json_str[:200]
            )
            
            message_id = await redis.xadd(
                self.stream_name,
                {
                    "event": event_json_str
                }
            )
            
            logger.debug(
                "event_published",
                event_id=event.event_id,
                event_type=event.event_type,
                stream=self.stream_name,
                message_id=message_id,
                correlation_id=event.correlation_id
            )
            
            # Also publish to WebSocket client if available (for low-latency delivery)
            try:
                from agent.api.websocket_client import get_websocket_client
                ws_client = await get_websocket_client()
                if ws_client and ws_client.is_connected:
                    # Format event for WebSocket (backend expects this format)
                    ws_message = {
                        "type": "agent_event",
                        "event_type": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                        "payload": event_data.get("payload", event_data),
                        "timestamp": event_data.get("timestamp", datetime.utcnow().isoformat()),
                        "event_id": event.event_id,
                        "correlation_id": event.correlation_id,
                    }
                    sent = await ws_client.send_event(ws_message)
                    if sent:
                        logger.debug(
                            "event_published_websocket",
                            event_id=event.event_id,
                            event_type=event.event_type,
                        )
            except Exception as ws_error:
                # Don't fail Redis publish if WebSocket fails
                logger.debug(
                    "event_websocket_publish_failed",
                    event_id=event.event_id,
                    event_type=event.event_type,
                    error=str(ws_error),
                    message="Event still published to Redis Stream"
                )
            
            return True
            
        except Exception as e:
            log_error_with_context(
                "event_publish_failed",
                error=e,
                component="event_bus",
                correlation_id=event.event_id if hasattr(event, 'event_id') else None,
                event_type=event.event_type.value if hasattr(event, 'event_type') and hasattr(event.event_type, 'value') else (str(event.event_type) if hasattr(event, 'event_type') else 'unknown')
            )
            return False
    
    def subscribe(self, event_type: EventType, handler: Callable[[BaseEvent], None]):
        """Subscribe to event type.
        
        Args:
            event_type: Event type to subscribe to
            handler: Async handler function
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        
        self.handlers[event_type].append(handler)
        
        logger.info(
            "event_handler_registered",
            event_type=event_type,
            handler=handler.__name__ if hasattr(handler, "__name__") else str(handler)
        )
    
    async def start_consuming(self):
        """Start consuming events from stream."""
        if self.running:
            logger.warning("event_bus_already_consuming")
            return
        
        self.running = True
        self._consuming_task = asyncio.create_task(self._consume_loop())
        
        logger.info("event_bus_consuming_started", stream=self.stream_name)
    
    async def _consume_loop(self):
        """Main consumption loop."""
        while self.running:
            try:
                redis = await get_redis()
                
                if redis is None:
                    logger.warning(
                        "event_consume_loop_paused",
                        message="Redis unavailable - consumption paused"
                    )
                    await asyncio.sleep(5)  # Wait longer if Redis is down
                    continue
                
                # Read from stream with consumer group
                messages = await redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=10,
                    block=1000  # Block for 1 second
                )
                
                if not messages:
                    continue
                
                # Process messages
                for stream, stream_messages in messages:
                    for message_id, message_data in stream_messages:
                        await self._process_message(message_id, message_data, redis)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error_with_context(
                    "event_consume_loop_error",
                    error=e,
                    component="event_bus",
                    stream=self.stream_name,
                    consumer_group=self.consumer_group
                )
                await asyncio.sleep(1)
    
    async def _move_to_dlq(self, redis: Redis, message_id: str, message_data: Dict[str, bytes], reason: str):
        """Move a message to the dead letter queue.
        
        Args:
            redis: Redis client
            message_id: Original message ID
            message_data: Original message data
            reason: Reason for moving to DLQ
        """
        try:
            # Try to extract event data if available
            event_data_str = "{}"
            try:
                event_json_bytes = message_data.get(b"event") or message_data.get("event".encode("utf-8"))
                if event_json_bytes:
                    if isinstance(event_json_bytes, bytes):
                        event_data_str = event_json_bytes.decode("utf-8", errors="replace")
                    else:
                        event_data_str = str(event_json_bytes)
            except Exception:
                pass
            
            await redis.xadd(
                self._dead_letter_stream,
                {
                    "original_message_id": message_id,
                    "failed_at": datetime.utcnow().isoformat() + "Z",
                    "reason": reason,
                    "event_data": event_data_str[:1000]  # Limit size
                }
            )
            logger.warning(
                "event_moved_to_dlq_validation",
                message_id=message_id,
                reason=reason,
                dlq_stream=self._dead_letter_stream
            )
        except Exception as e:
            logger.error(
                "event_dlq_move_failed",
                message_id=message_id,
                reason=reason,
                error=str(e),
                exc_info=True
            )
    
    async def _process_message(self, message_id: str, message_data: Dict[str, bytes], redis: Redis):
        """Process a single message.
        
        Args:
            message_id: Redis message ID
            message_data: Message data
            redis: Redis client (must be provided, already checked for None)
        """
        try:
            # Extract retry count from message metadata
            retry_count = 0
            if b"retry_count" in message_data:
                try:
                    retry_count = int(message_data[b"retry_count"].decode("utf-8"))
                except (ValueError, AttributeError):
                    retry_count = 0
            
            # Deserialize event - Redis Streams returns data as bytes
            # Check all possible key formats (some Redis clients use different encodings)
            event_json_bytes = None
            for key_variant in [b"event", "event".encode("utf-8"), b"event".decode("utf-8")]:
                if isinstance(key_variant, bytes):
                    event_json_bytes = message_data.get(key_variant)
                elif isinstance(key_variant, str):
                    # Try both string and bytes versions
                    event_json_bytes = message_data.get(key_variant.encode("utf-8")) or message_data.get(key_variant)
                
                if event_json_bytes:
                    break
            
            # If still not found, check if message_data itself contains the event
            if not event_json_bytes:
                # Sometimes Redis returns the data directly in message_data
                # Check if there's a single key-value pair that might be the event
                if len(message_data) == 1:
                    event_json_bytes = list(message_data.values())[0]
                elif len(message_data) == 0:
                    logger.warning(
                        "event_validation_skipped",
                        message_id=message_id,
                        reason="Empty message data",
                        message_keys=list(message_data.keys()) if isinstance(message_data, dict) else "not_dict"
                    )
                    await redis.xack(self.stream_name, self.consumer_group, message_id)
                    return
            
            # Debug: Log raw message data to understand format
            if event_json_bytes:
                try:
                    preview = event_json_bytes[:200].decode("utf-8", errors="replace") if isinstance(event_json_bytes, bytes) else str(event_json_bytes)[:200]
                except Exception:
                    preview = f"<bytes length={len(event_json_bytes) if isinstance(event_json_bytes, bytes) else 'unknown'}>"
            else:
                preview = None
                
            logger.debug(
                "event_message_received",
                message_id=message_id,
                message_keys=[k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k) for k in (list(message_data.keys()) if isinstance(message_data, dict) else [])],
                event_json_length=len(event_json_bytes) if event_json_bytes else 0,
                event_json_preview=preview,
                event_json_type=type(event_json_bytes).__name__ if event_json_bytes else None
            )
            
            if not event_json_bytes or (isinstance(event_json_bytes, bytes) and len(event_json_bytes) == 0):
                logger.warning(
                    "event_validation_skipped",
                    message_id=message_id,
                    reason="No event data in message",
                    message_keys=[k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k) for k in (list(message_data.keys()) if isinstance(message_data, dict) else [])],
                    message_data_type=type(message_data).__name__
                )
                # Move message with no event data to DLQ
                await self._move_to_dlq(redis, message_id, message_data, "No event data in message")
                await redis.xack(self.stream_name, self.consumer_group, message_id)
                return
            
            # Decode bytes to string if needed
            try:
                if isinstance(event_json_bytes, bytes):
                    event_json_str = event_json_bytes.decode("utf-8")
                else:
                    event_json_str = str(event_json_bytes)
                
                # Parse JSON
                event_dict = json.loads(event_json_str)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as e:
                logger.error(
                    "event_deserialization_failed",
                    message_id=message_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    event_json_preview=preview,
                    event_json_type=type(event_json_bytes).__name__,
                    exc_info=True
                )
                # Move malformed message to DLQ instead of just acknowledging
                await self._move_to_dlq(redis, message_id, message_data, f"Deserialization failed: {str(e)}")
                await redis.xack(self.stream_name, self.consumer_group, message_id)
                return
            
            # Validate event dictionary - check if it's empty or missing required fields
            if not event_dict or not isinstance(event_dict, dict):
                logger.warning(
                    "event_validation_skipped",
                    message_id=message_id,
                    reason="Empty or invalid event dictionary",
                    event_data=str(event_dict)[:200] if event_dict else "empty",
                    event_dict_type=type(event_dict).__name__
                )
                # Move invalid message to DLQ instead of just acknowledging
                await self._move_to_dlq(redis, message_id, message_data, "Empty or invalid event dictionary")
                await redis.xack(self.stream_name, self.consumer_group, message_id)
                return
            
            # Check for required BaseEvent fields (event_type and source)
            if "event_type" not in event_dict or "source" not in event_dict:
                logger.warning(
                    "event_validation_skipped",
                    message_id=message_id,
                    reason="Missing required fields (event_type or source)",
                    event_data=str(event_dict)[:200]
                )
                # Move invalid message to DLQ instead of just acknowledging
                await self._move_to_dlq(redis, message_id, message_data, "Missing required fields (event_type or source)")
                await redis.xack(self.stream_name, self.consumer_group, message_id)
                return
            
            # Get event class name
            event_class_name = event_dict.pop("_event_class", "BaseEvent")
            
            # Import and get event class
            from agent.events.schemas import (
                BaseEvent, MarketTickEvent, CandleClosedEvent,
                FeatureRequestEvent, FeatureComputedEvent,
                ModelPredictionRequestEvent, ModelPredictionEvent,
                ModelPredictionCompleteEvent, ReasoningRequestEvent,
                ReasoningCompleteEvent, DecisionReadyEvent,
                RiskAlertEvent, RiskApprovedEvent, EmergencyStopEvent,
                OrderSubmittedEvent, OrderFillEvent, ExecutionFailedEvent,
                AgentCommandEvent, StateTransitionEvent,
                ModelWeightUpdateEvent, StrategyAdaptationEvent,
                LearningCompleteEvent, PositionClosedEvent
            )
            
            event_class_map = {
                "BaseEvent": BaseEvent,
                "MarketTickEvent": MarketTickEvent,
                "CandleClosedEvent": CandleClosedEvent,
                "FeatureRequestEvent": FeatureRequestEvent,
                "FeatureComputedEvent": FeatureComputedEvent,
                "ModelPredictionRequestEvent": ModelPredictionRequestEvent,
                "ModelPredictionEvent": ModelPredictionEvent,
                "ModelPredictionCompleteEvent": ModelPredictionCompleteEvent,
                "ReasoningRequestEvent": ReasoningRequestEvent,
                "ReasoningCompleteEvent": ReasoningCompleteEvent,
                "DecisionReadyEvent": DecisionReadyEvent,
                "RiskAlertEvent": RiskAlertEvent,
                "RiskApprovedEvent": RiskApprovedEvent,
                "EmergencyStopEvent": EmergencyStopEvent,
                "OrderSubmittedEvent": OrderSubmittedEvent,
                "OrderFillEvent": OrderFillEvent,
                "ExecutionFailedEvent": ExecutionFailedEvent,
                "AgentCommandEvent": AgentCommandEvent,
                "StateTransitionEvent": StateTransitionEvent,
                "ModelWeightUpdateEvent": ModelWeightUpdateEvent,
                "StrategyAdaptationEvent": StrategyAdaptationEvent,
                "LearningCompleteEvent": LearningCompleteEvent,
                "PositionClosedEvent": PositionClosedEvent,
            }
            
            event_class = event_class_map.get(event_class_name, BaseEvent)
            
            # Handle datetime strings
            if "timestamp" in event_dict and isinstance(event_dict["timestamp"], str):
                event_dict["timestamp"] = datetime.fromisoformat(event_dict["timestamp"])
            
            # Create event instance with error handling
            try:
                event = event_class(**event_dict)
            except Exception as e:
                log_error_with_context(
                    "event_instantiation_failed",
                    error=e,
                    component="event_bus",
                    message_id=str(message_id) if message_id else None,
                    event_class_name=event_class_name,
                    event_dict_keys=list(event_dict.keys()) if isinstance(event_dict, dict) else None
                )
                await redis.xack(self.stream_name, self.consumer_group, message_id)
                return
            
            # Get handlers for this event type
            handlers = self.handlers.get(event.event_type, [])
            
            if not handlers:
                logger.debug(
                    "event_no_handlers",
                    event_type=event.event_type,
                    event_id=event.event_id
                )
                # Acknowledge message even if no handlers
                await redis.xack(self.stream_name, self.consumer_group, message_id)
                return
            
            # Process with handlers
            success = False
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                    success = True
                except Exception as e:
                    log_error_with_context(
                        "event_handler_error",
                        error=e,
                        component="event_bus",
                        correlation_id=event.event_id if hasattr(event, "event_id") else None,
                        event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                        handler=handler.__name__ if hasattr(handler, "__name__") else str(handler)
                    )
            
            # Acknowledge message if at least one handler succeeded
            if success:
                await redis.xack(self.stream_name, self.consumer_group, message_id)
            else:
                # Handle failed message with retry logic
                await self._handle_failed_message(message_id, event, redis, retry_count)
                
        except Exception as e:
            logger.error(
                "event_process_message_error",
                message_id=message_id,
                error=str(e),
                exc_info=True
            )
            # Extract retry count if available
            retry_count = 0
            if b"retry_count" in message_data:
                try:
                    retry_count = int(message_data[b"retry_count"].decode("utf-8"))
                except (ValueError, AttributeError):
                    pass
            # Move to dead letter queue or retry
            await self._handle_failed_message(message_id, None, redis, retry_count)
    
    async def _handle_failed_message(
        self, 
        message_id: str, 
        event: Optional[BaseEvent], 
        redis: Redis,
        current_retry_count: int = 0
    ):
        """Handle failed message with retry logic and exponential backoff.
        
        Args:
            message_id: Redis message ID
            event: Event that failed (if available)
            redis: Redis client
            current_retry_count: Current retry attempt count
        """
        try:
            # Check if we should retry or move to DLQ
            if current_retry_count < self._max_retries:
                # Retry with exponential backoff
                new_retry_count = current_retry_count + 1
                backoff_seconds = min(2 ** current_retry_count, 300)  # Cap at 5 minutes
                
                logger.warning(
                    "event_retry_scheduled",
                    message_id=message_id,
                    retry_count=new_retry_count,
                    max_retries=self._max_retries,
                    backoff_seconds=backoff_seconds,
                    event_type=event.event_type if event else "unknown"
                )
                
                # Re-queue message with updated retry count after backoff delay
                await asyncio.sleep(backoff_seconds)
                
                # Re-add message to stream with retry count
                if event:
                    event_data = event.dict()
                    event_data["_event_class"] = event.__class__.__name__
                    
                    await redis.xadd(
                        self.stream_name,
                        {
                            "event": json.dumps(event_data, default=str),
                            "retry_count": str(new_retry_count),
                            "original_message_id": message_id,
                            "retry_at": datetime.utcnow().isoformat()
                        }
                    )
                    
                    # Acknowledge original message (it's been re-queued)
                    await redis.xack(self.stream_name, self.consumer_group, message_id)
                    return
                else:
                    # If event is None, we can't retry - move to DLQ
                    logger.error(
                        "event_retry_failed_no_event",
                        message_id=message_id,
                        message="Cannot retry message without event data"
                    )
                    # Fall through to DLQ logic by setting retry count to max
                    current_retry_count = self._max_retries
            else:
                # Max retries exceeded, move to dead letter queue
                logger.error(
                    "event_moved_to_dlq",
                    message_id=message_id,
                    retry_count=current_retry_count,
                    max_retries=self._max_retries,
                    event_type=event.event_type if event else "unknown"
                )
                
                await redis.xadd(
                    self._dead_letter_stream,
                    {
                        "original_message_id": message_id,
                        "retry_count": str(current_retry_count),
                        "failed_at": datetime.utcnow().isoformat(),
                        "event": json.dumps(event.dict(), default=str) if event else "{}"
                    }
                )
                
                # Acknowledge original message
                await redis.xack(self.stream_name, self.consumer_group, message_id)
            
        except Exception as e:
            logger.error(
                "event_dlq_failed",
                message_id=message_id,
                error=str(e),
                exc_info=True
            )


# Global event bus instance
event_bus = EventBus()

