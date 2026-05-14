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
    
    async def xgroup_create(
        self,
        name: str | None = None,
        groupname: str | None = None,
        stream_name: str | None = None,
        group_name: str | None = None,
        id: str = "0",
        mkstream: bool = True,
    ):
        """Create consumer group (matches redis ``name=`` / ``groupname=`` kwargs)."""
        sn = name or stream_name
        gn = groupname or group_name
        if not sn or not gn:
            return
        if sn not in self.groups:
            self.groups[sn] = set()
        self.groups[sn].add(gn)
    
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


@pytest_asyncio.fixture
async def redis_event_bus(mock_redis, monkeypatch):
    """Create event bus with mock Redis and patched ``get_redis``."""
    async def _get_redis():
        return mock_redis

    monkeypatch.setattr("agent.core.redis_config.get_redis", _get_redis)
    import importlib

    event_bus_module = importlib.import_module("agent.events.event_bus")
    monkeypatch.setattr(event_bus_module, "get_redis", _get_redis)
    await mock_redis.xgroup_create(name="test_stream", groupname="test_group", id="0", mkstream=True)
    return EventBus(stream_name="test_stream", consumer_group="test_group")


@pytest.mark.asyncio
async def test_event_publish_consume_cycle(redis_event_bus, mock_redis):
    """Test complete event publish and consume cycle."""
    # Create test event
    event = AgentCommandEvent(
        source="integration_test",
        payload={
            "command": "get_status",
            "parameters": {"test": "data"},
            "request_id": "req-1",
        },
    )
    
    # Subscribe handler
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish event
    published = await redis_event_bus.publish(event)
    assert published is True
    
    # Verify event was added to stream
    assert len(mock_redis.xadd_calls) == 1
    stream_name, fields = mock_redis.xadd_calls[0]
    assert stream_name == "test_stream"
    assert "event" in fields

    # Process messages manually (simulating consume loop) — avoid ``start_consuming`` tight loop in tests.
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for message_id, message_data in stream_messages:
            await redis_event_bus._process_message(message_id.decode("utf-8"), message_data, mock_redis)
    
    # Verify event was received
    assert len(received_events) == 1
    assert isinstance(received_events[0], AgentCommandEvent)
    assert received_events[0].payload["command"] == "get_status"
    assert received_events[0].payload["parameters"] == {"test": "data"}


@pytest.mark.asyncio
async def test_event_deserialization_from_redis(redis_event_bus, mock_redis):
    """Test event deserialization from Redis Stream format."""
    # Create event and serialize it
    event = MarketTickEvent(
        source="integration_test",
        payload={
            "symbol": "BTCUSD",
            "price": 50000.0,
            "timestamp": datetime.now().isoformat(),
        },
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
    
    redis_event_bus.subscribe(EventType.MARKET_TICK, handler)
    
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
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify event was deserialized correctly
    assert len(received_events) == 1
    assert isinstance(received_events[0], MarketTickEvent)
    assert received_events[0].payload["symbol"] == "BTCUSD"
    assert received_events[0].payload["price"] == 50000.0


@pytest.mark.asyncio
async def test_event_with_unicode_characters(redis_event_bus, mock_redis):
    """Test event pipeline with Unicode characters."""
    event = AgentCommandEvent(
        source="integration_test",
        payload={
            "command": "get_status",
            "parameters": {"message": "Test with Unicode: ✓ ⚠ ✗ ✅"},
            "request_id": "req-unicode",
        },
    )
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish event
    await redis_event_bus.publish(event)
    
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
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify Unicode characters are preserved
    assert len(received_events) == 1
    assert "✓ ⚠ ✗ ✅" in received_events[0].payload["parameters"]["message"]


@pytest.mark.asyncio
async def test_multiple_events_pipeline(redis_event_bus, mock_redis):
    """Test processing multiple events through pipeline."""
    events = [
        AgentCommandEvent(
            source="integration_test",
            payload={
                "command": "get_status",
                "parameters": {"id": 1},
                "request_id": "r1",
            },
        ),
        AgentCommandEvent(
            source="integration_test",
            payload={
                "command": "get_status",
                "parameters": {"id": 2},
                "request_id": "r2",
            },
        ),
        AgentCommandEvent(
            source="integration_test",
            payload={
                "command": "get_status",
                "parameters": {"id": 3},
                "request_id": "r3",
            },
        ),
    ]
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish all events
    for event in events:
        await redis_event_bus.publish(event)
    
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
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify all events were received
    assert len(received_events) == 3
    assert all(isinstance(evt, AgentCommandEvent) for evt in received_events)
    assert [evt.payload["parameters"]["id"] for evt in received_events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_event_acknowledgment(redis_event_bus, mock_redis):
    """Test that events are properly acknowledged after processing."""
    event = AgentCommandEvent(
        source="integration_test",
        payload={
            "command": "get_status",
            "parameters": {"test": "data"},
            "request_id": "req-ack",
        },
    )
    
    async def handler(evt):
        pass  # Do nothing
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
    # Publish and process
    await redis_event_bus.publish(event)
    
    messages = await mock_redis.xreadgroup(
        groupname="test_group",
        consumername="test_consumer",
        streams={"test_stream": ">"},
        count=10,
        block=100
    )
    
    for stream, stream_messages in messages:
        for msg_id, msg_data in stream_messages:
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Verify message was acknowledged
    assert len(mock_redis.acks) > 0
    assert any(ack[0] == "test_stream" for ack in mock_redis.acks)


@pytest.mark.asyncio
async def test_empty_event_handling(redis_event_bus, mock_redis):
    """Test handling of empty events."""
    # Manually add empty event to stream
    await mock_redis.xadd("test_stream", {"event": "{}"})
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
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
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Empty event should be skipped, not processed
    assert len(received_events) == 0
    # But should be acknowledged
    assert len(mock_redis.acks) > 0


@pytest.mark.asyncio
async def test_corrupted_event_handling(redis_event_bus, mock_redis):
    """Test handling of corrupted events."""
    # Add corrupted event data
    await mock_redis.xadd("test_stream", {"event": "{invalid json"})
    
    received_events = []
    
    async def handler(evt):
        received_events.append(evt)
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
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
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Corrupted event should be skipped
    assert len(received_events) == 0
    # But should be acknowledged to prevent retry loops
    assert len(mock_redis.acks) > 0


@pytest.mark.asyncio
async def test_event_retry_count_handling(redis_event_bus, mock_redis):
    """Test handling of events with retry count metadata."""
    event = AgentCommandEvent(
        source="integration_test",
        payload={
            "command": "get_status",
            "parameters": {"test": "data"},
            "request_id": "req-retry",
        },
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
    
    redis_event_bus.subscribe(EventType.AGENT_COMMAND, handler)
    
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
            await redis_event_bus._process_message(msg_id.decode("utf-8"), msg_data, mock_redis)
    
    # Event should be processed despite retry count
    assert len(received_events) == 1

