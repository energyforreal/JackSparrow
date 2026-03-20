"""Unit tests for event bus deserialization."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest
import pytest_asyncio

# Provide minimal config so agent settings can initialize during tests
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from agent.events.event_bus import EventBus
from agent.events.schemas import (
    BaseEvent,
    AgentCommandEvent,
    MarketTickEvent,
    EventType
)


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.streams = {}
        self.acks = []
        self.xadd_calls = []
    
    async def xadd(self, stream_name: str, fields: dict):
        """Add message to stream."""
        if stream_name not in self.streams:
            self.streams[stream_name] = []
        
        message_id = f"1234567890-{len(self.streams[stream_name])}"
        self.streams[stream_name].append((message_id, fields))
        self.xadd_calls.append((stream_name, fields))
        return message_id
    
    async def xreadgroup(self, groupname: str, consumername: str, streams: dict, count: int = 10, block: int = 1000):
        """Read messages from stream."""
        results = []
        for stream_name, position in streams.items():
            if stream_name in self.streams:
                messages = []
                for msg_id, fields in self.streams[stream_name]:
                    # Convert fields dict to bytes format as Redis would return
                    message_data = {}
                    for key, value in fields.items():
                        if isinstance(key, str):
                            message_data[key.encode("utf-8")] = value.encode("utf-8") if isinstance(value, str) else value
                        else:
                            message_data[key] = value.encode("utf-8") if isinstance(value, str) else value
                    messages.append((msg_id, message_data))
                if messages:
                    results.append((stream_name.encode("utf-8"), messages))
        return results
    
    async def xack(self, stream_name: str, group_name: str, message_id: str):
        """Acknowledge message."""
        self.acks.append((stream_name, group_name, message_id))
    
    async def xgroup_create(self, stream_name: str, group_name: str, id: str = "0", mkstream: bool = True):
        """Create consumer group."""
        pass
    
    async def close(self):
        """Close connection."""
        pass


@pytest.fixture
def mock_redis():
    """Create mock Redis instance."""
    return MockRedis()


@pytest.fixture
def event_bus(mock_redis):
    """Create event bus with mock Redis."""
    bus = EventBus(stream_name="test_stream", consumer_group="test_group")
    
    # Patch get_redis to return mock_redis
    async def get_redis():
        return mock_redis
    
    bus._get_redis = get_redis
    return bus


@pytest.mark.asyncio
async def test_deserialize_event_with_bytes_key(event_bus, mock_redis):
    """Test deserialization with bytes key format."""
    # Create test event
    event = AgentCommandEvent(
        command="get_status",
        payload={"test": "data"}
    )
    
    # Serialize event
    event_data = event.model_dump()
    event_data["_event_class"] = "AgentCommandEvent"
    event_json = json.dumps(event_data, default=str)
    
    # Create message data as Redis would return (bytes keys)
    message_data = {
        b"event": event_json.encode("utf-8")
    }
    
    # Mock handler
    handler_called = []
    async def test_handler(evt):
        handler_called.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, test_handler)
    
    # Process message
    await event_bus._process_message("test-msg-1", message_data, mock_redis)
    
    # Verify handler was called
    assert len(handler_called) == 1
    assert isinstance(handler_called[0], AgentCommandEvent)
    assert handler_called[0].command == "get_status"
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-1")]


@pytest.mark.asyncio
async def test_deserialize_event_with_string_key(event_bus, mock_redis):
    """Test deserialization with string key format."""
    event = MarketTickEvent(
        symbol="BTCUSD",
        price=50000.0,
        timestamp=datetime.now()
    )
    
    event_data = event.model_dump()
    event_data["_event_class"] = "MarketTickEvent"
    event_json = json.dumps(event_data, default=str)
    
    # Create message data with string key (some Redis clients return this)
    message_data = {
        "event": event_json  # String key instead of bytes
    }
    
    handler_called = []
    async def test_handler(evt):
        handler_called.append(evt)
    
    event_bus.subscribe(EventType.MARKET_TICK, test_handler)
    
    await event_bus._process_message("test-msg-2", message_data, mock_redis)
    
    assert len(handler_called) == 1
    assert isinstance(handler_called[0], MarketTickEvent)
    assert handler_called[0].symbol == "BTCUSD"
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-2")]


@pytest.mark.asyncio
async def test_deserialize_empty_event(event_bus, mock_redis):
    """Test handling of empty event data."""
    message_data = {
        b"event": b"{}"  # Empty JSON
    }
    
    await event_bus._process_message("test-msg-3", message_data, mock_redis)
    
    # Should acknowledge and skip
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-3")]


@pytest.mark.asyncio
async def test_deserialize_missing_event_key(event_bus, mock_redis):
    """Test handling when event key is missing."""
    message_data = {
        b"other_key": b"some_value"
    }
    
    await event_bus._process_message("test-msg-4", message_data, mock_redis)
    
    # Should acknowledge and skip
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-4")]


@pytest.mark.asyncio
async def test_deserialize_corrupted_json(event_bus, mock_redis):
    """Test handling of corrupted JSON."""
    message_data = {
        b"event": b"{invalid json"
    }
    
    await event_bus._process_message("test-msg-5", message_data, mock_redis)
    
    # Should acknowledge and skip (error logged)
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-5")]


@pytest.mark.asyncio
async def test_deserialize_missing_required_fields(event_bus, mock_redis):
    """Test handling when required fields are missing."""
    # Create event data without required fields
    incomplete_data = {
        "event_id": "test-id",
        # Missing event_type and source
    }
    event_json = json.dumps(incomplete_data)
    
    message_data = {
        b"event": event_json.encode("utf-8")
    }
    
    await event_bus._process_message("test-msg-6", message_data, mock_redis)
    
    # Should acknowledge and skip
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-6")]


@pytest.mark.asyncio
async def test_deserialize_event_instantiation_failure(event_bus, mock_redis):
    """Test handling when event instantiation fails."""
    # Create event data with invalid field values
    invalid_data = {
        "event_id": "test-id",
        "event_type": "agent_command",
        "source": "test",
        "timestamp": datetime.now().isoformat(),
        "_event_class": "AgentCommandEvent",
        "command": "get_status",
        "payload": {"invalid": "data"},
        # Add invalid field that would cause instantiation to fail
        "invalid_field": object()  # This can't be serialized properly
    }
    
    # Manually serialize to avoid validation errors
    event_json = json.dumps(invalid_data, default=str)
    
    message_data = {
        b"event": event_json.encode("utf-8")
    }
    
    await event_bus._process_message("test-msg-7", message_data, mock_redis)
    
    # Should acknowledge and skip (error logged)
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-7")]


@pytest.mark.asyncio
async def test_deserialize_with_retry_count(event_bus, mock_redis):
    """Test deserialization with retry count metadata."""
    event = AgentCommandEvent(
        command="get_status",
        payload={"test": "data"}
    )
    
    event_data = event.model_dump()
    event_data["_event_class"] = "AgentCommandEvent"
    event_json = json.dumps(event_data, default=str)
    
    message_data = {
        b"event": event_json.encode("utf-8"),
        b"retry_count": b"2"
    }
    
    handler_called = []
    async def test_handler(evt):
        handler_called.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, test_handler)
    
    await event_bus._process_message("test-msg-8", message_data, mock_redis)
    
    assert len(handler_called) == 1
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-8")]


@pytest.mark.asyncio
async def test_deserialize_single_key_value_pair(event_bus, mock_redis):
    """Test deserialization when message_data has single key-value pair."""
    event = AgentCommandEvent(
        command="get_status",
        payload={"test": "data"}
    )
    
    event_data = event.model_dump()
    event_data["_event_class"] = "AgentCommandEvent"
    event_json = json.dumps(event_data, default=str)
    
    # Simulate Redis returning single key-value pair
    message_data = {
        b"event": event_json.encode("utf-8")
    }
    
    handler_called = []
    async def test_handler(evt):
        handler_called.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, test_handler)
    
    await event_bus._process_message("test-msg-9", message_data, mock_redis)
    
    assert len(handler_called) == 1
    assert isinstance(handler_called[0], AgentCommandEvent)


@pytest.mark.asyncio
async def test_deserialize_empty_message_data(event_bus, mock_redis):
    """Test handling of completely empty message data."""
    message_data = {}
    
    await event_bus._process_message("test-msg-10", message_data, mock_redis)
    
    # Should acknowledge and skip
    assert mock_redis.acks == [("test_stream", "test_group", "test-msg-10")]


@pytest.mark.asyncio
async def test_deserialize_unicode_characters(event_bus, mock_redis):
    """Test deserialization with Unicode characters in event data."""
    event = AgentCommandEvent(
        command="get_status",
        payload={"message": "Test with Unicode: ✓ ⚠ ✗ ✅"}
    )
    
    event_data = event.model_dump()
    event_data["_event_class"] = "AgentCommandEvent"
    event_json = json.dumps(event_data, default=str)
    
    message_data = {
        b"event": event_json.encode("utf-8")
    }
    
    handler_called = []
    async def test_handler(evt):
        handler_called.append(evt)
    
    event_bus.subscribe(EventType.AGENT_COMMAND, test_handler)
    
    await event_bus._process_message("test-msg-11", message_data, mock_redis)
    
    assert len(handler_called) == 1
    assert "✓ ⚠ ✗ ✅" in handler_called[0].payload["message"]

