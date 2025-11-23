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

from agent.core.redis import get_redis
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
            logger.error(
                "event_bus_consumer_group_connection_error",
                stream=self.stream_name,
                group=self.consumer_group,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise  # Re-raise connection errors as they indicate a real problem
        except Exception as e:
            # Catch any other unexpected exceptions
            logger.error(
                "event_bus_consumer_group_unexpected_error",
                stream=self.stream_name,
                group=self.consumer_group,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
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
            
            # Serialize event
            event_data = event.dict()
            event_data["_event_class"] = event.__class__.__name__
            
            # Publish to Redis Stream
            message_id = await redis.xadd(
                self.stream_name,
                {
                    "event": json.dumps(event_data, default=str)
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
            
            return True
            
        except Exception as e:
            logger.error(
                "event_publish_failed",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
                exc_info=True
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
                logger.error(
                    "event_consume_loop_error",
                    error=str(e),
                    exc_info=True
                )
                await asyncio.sleep(1)
    
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
            
            # Deserialize event
            event_json = message_data.get(b"event", b"{}")
            event_dict = json.loads(event_json.decode("utf-8"))
            
            # Validate event dictionary - check if it's empty or missing required fields
            if not event_dict or not isinstance(event_dict, dict):
                logger.warning(
                    "event_validation_skipped",
                    message_id=message_id,
                    reason="Empty or invalid event dictionary",
                    event_data=str(event_dict)[:200] if event_dict else "empty"
                )
                # Acknowledge corrupted message to prevent retry loops
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
                # Acknowledge corrupted message to prevent retry loops
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
            
            event = event_class(**event_dict)
            
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
                    logger.error(
                        "event_handler_error",
                        event_id=event.event_id,
                        event_type=event.event_type,
                        handler=handler.__name__ if hasattr(handler, "__name__") else str(handler),
                        error=str(e),
                        exc_info=True
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

