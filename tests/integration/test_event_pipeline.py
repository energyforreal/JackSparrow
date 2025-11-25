"""Integration tests for event pipeline."""

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Provide minimal config so agent settings can initialize during tests
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from agent.events.event_bus import EventBus
from agent.events.schemas import (
    AgentCommandEvent,
    MarketTickEvent,
    EventType
)


class MockRedisStreams:
    """Mock Redis client with Streams support for integration tests."""
    
    def __init__(self):
        self.streams = {}
        self.groups = {}
        self.acks = []
        self.xadd_calls = []
    
    async def xadd(self, stream_name: str, fields: dict):
        """Add message to stream."""
        if stream_name not in self.streams:
            self.streams[stream_name] = []
        
        message_id = f"{int(time.time() * 1000)}-{len(self.streams[stream_name])}"
        self.streams[stream_name].append((message_id, fields))
        self.xadd_calls.append((stream_name, fields))
        return message_id
    
    async def xreadgroup(self, groupname: str, consumername: str, streams: dict, count: int = 10, block: int = 1000):
        """Read messages from stream."""
        results = []
        for stream_name, position in streams.items():
            if stream_name in self.streams and position == ">":
                messages = []
                for msg_id, fields in self.streams[stream_name]:
                    # Convert fields dict to bytes format as Redis would return
                    message_data = {}
                    for key, value in fields.items():
                        if isinstance(key, str):
                            message_data[key.encode("utf-8")] = value.encode("utf-8") if isinstance(value, str) else value
                        else:
                            message_data[key] = value.encode("utf-8") if isinstance(value, str) else value
                    messages.append((msg_id.encode("utf-8"), message_data))
                if messages:
                    results.append((stream_name.encode("utf-8"), messages))
        return results
    
    async def xack(self, stream_name: str, group_name: str, message_id: str):
        """Acknowledge message."""
        self.acks.append((stream_name, group_name, message_id))
    
    async def xgroup_create(self, stream_name: str, group_name: str, id: str = "0", mkstream: bool = True):
        """Create consumer group."""
        if stream_name not in self.groups:
            self.groups[stream_name] = set()
        self.groups[stream_name].add(group_name)
    
    async def close(self):
        """Close connection."""
        pass
    
    async def ping(self):
        """Ping server."""
        return True


@pytest.fixture
def mock_redis():
    """Create mock Redis instance."""
    return MockRedisStreams()


@pytest.fixture
def event_bus(mock_redis):
    """Create event bus with mock Redis."""
    bus = EventBus(stream_name="test_stream", consumer_group="test_group")
    
    # Patch get_redis to return mock_redis
    async def get_redis():
        return mock_redis
    
    # Create consumer group
    asyncio.create_task(mock_redis.xgroup_create("test_stream", "test_group"))
    
    return bus


@pytest.mark.asyncio
async def test_event_publish_consume_cycle(event_bus, mock_redis):
    """Test complete event publish and consume cycle."""
    # Create test event
    event = AgentCommandEvent(
        command="get_status",
        payload={"test": "data"}
    )
    
    # Subscribe handler
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish event
    published = await event_bus.publish(event)
    assert published is True
    
    # Verify event was added to stream
    assert len(mock_redis.xadd_calls) == 1
    stream_name, fields = mock_redis.xadd_calls[0]
    assert stream_name == "test_stream"
    assert "event" in fields
    
    # Start consuming
    await event_bus.start_consuming()
    
    # Give it time to process
    await asyncio.sleep(0.1)
    
    # Process messages manually (simulating consume loop)
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for message_id, message_data in stream_messages:
            await event_bus._process_message(message_id.decode("utf-8"), message_data, mock_redis)
    
    # Verify event was received
    assert len(received_events) == 1
    assert isinstance(received_events[0], AgentCommandEvent)
    assert received_events[0].command == "get_status"
    assert received_events[0].payload == {"test": "data"}


@pytest.mark.asyncio
async def test_event_deserialization_from_redis(event_bus, mock_redis):
    """Test event deserialization from Redis Stream format."""
    # Create event and serialize it
    event = MarketTickEvent(
        symbol="BTCUSD",
        price=50000.0,
        timestamp=datetime.now()
    )
    
    event_data = event.model_dump()
    event_data["_event_class"] = "MarketTickEvent"
    event_json = json.dumps(event_data, default=str)
    
    # Manually add to stream (simulating Redis)
    message_id = await mock_redis.xadd("test_stream", {"event": event_json})
    
    # Subscribe handler
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.MARKET_TICK, handler)
    
    # Read and process message
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify event was deserialized correctly
    assert len(received_events) == 1
    assert isinstance(received_events[0], MarketTickEvent)
    assert received_events[0].symbol == "BTCUSD"
    assert received_events[0].price == 50000.0


@pytest.mark.asyncio
async def test_event_with_unicode_characters(event_bus, mock_redis):
    """Test event pipeline with Unicode characters."""
    event = AgentCommandEvent(
        command="get_status",
        payload={"message": "Test with Unicode: ✓ ⚠ ✗ ✅"}
    )
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish event
    await event_bus.publish(event)
    
    # Process message
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify Unicode characters are preserved
    assert len(received_events) == 1
    assert "✓ ⚠ ✗ ✅" in received_events[0].payload["message"]


@pytest.mark.asyncio
async def test_multiple_events_pipeline(event_bus, mock_redis):
    """Test processing multiple events through pipeline."""
    events = [
        AgentCommandEvent(command="get_status", payload={"id": 1}),
        AgentCommandEvent(command="get_status", payload={"id": 2}),
        AgentCommandEvent(command="get_status", payload={"id": 3}),
    ]
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish all events
    for event in events:
        await event_bus.publish(event)
    
    # Process all messages
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify all events were received
    assert len(received_events) == 3
    assert all(isinstance(evt, AgentCommandEvent) for evt in received_events)
    assert [evt.payload["id"] for evt in received_events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_event_acknowledgment(event_bus, mock_redis):
    """Test that events are properly acknowledged after processing."""
    event = AgentCommandEvent(
        command="get_status",
        payload={"test": "data"}
    )
    
    async def handler(evt):
        pass  # Do nothing
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish and process
    await event_bus.publish(event)
    
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify message was acknowledged
    assert len(mock_redis.acks) > 0
    assert any(ack[0] == "test_stream" for ack in mock_redis.acks)


@pytest.mark.asyncio
async def test_empty_event_handling(event_bus, mock_redis):
    """Test handling of empty events."""
    # Manually add empty event to stream
    await mock_redis.xadd("test_stream", {"event": "{}"})
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Process message
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Empty event should be skipped, not processed
    assert len(received_events) == 0
    # But should be acknowledged
    assert len(mock_redis.acks) > 0


@pytest.mark.asyncio
async def test_corrupted_event_handling(event_bus, mock_redis):
    """Test handling of corrupted events."""
    # Add corrupted event data
    await mock_redis.xadd("test_stream", {"event": "{invalid json"})
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Process message
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Corrupted event should be skipped
    assert len(received_events) == 0
    # But should be acknowledged to prevent retry loops
    assert len(mock_redis.acks) > 0


@pytest.mark.asyncio
async def test_event_retry_count_handling(event_bus, mock_redis):
    """Test handling of events with retry count metadata."""
    event = AgentCommandEvent(
        command="get_status",
        payload={"test": "data"}
    )
    
    event_data = event.model_dump()
    event_data["_event_class"] = "AgentCommandEvent"
    event_json = json.dumps(event_data, default=str)
    
    # Add event with retry count
    message_id = await mock_redis.xadd("test_stream", {
        "event": event_json,
        "retry_count": "2"
    })
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Process message
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Event should be processed despite retry count
    assert len(received_events) == 1

