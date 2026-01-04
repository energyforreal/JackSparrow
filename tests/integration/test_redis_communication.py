"""
Integration tests for backend-agent Redis communication.

Tests the command/response mechanism between backend and agent services.
"""

import pytest
import asyncio
import json
import uuid
from typing import Dict, Any, Optional

from backend.core.redis import enqueue_command, get_response, get_redis
from agent.core.redis_config import get_redis as agent_get_redis


@pytest.mark.asyncio
async def test_command_response_mechanism():
    """Test that backend can send command and receive response from agent."""
    
    # Get Redis connections
    backend_redis = await get_redis()
    agent_redis = await agent_get_redis()
    
    if not backend_redis or not agent_redis:
        pytest.skip("Redis not available for integration test")
    
    # Generate unique request ID
    request_id = str(uuid.uuid4())
    
    # Create test command
    command = {
        "request_id": request_id,
        "command": "test_command",
        "parameters": {"test": "data"},
        "timestamp": 1234567890.0
    }
    
    # Simulate agent receiving command and sending response
    # In real scenario, agent would process command and send response
    test_response = {
        "request_id": request_id,
        "status": "success",
        "result": {"message": "test response"}
    }
    
    # Agent sends response using setex (current mechanism)
    await agent_redis.setex(
        f"response:{request_id}",
        120,  # 2 minute TTL
        json.dumps(test_response)
    )
    
    # Backend polls for response
    response = await get_response(request_id, timeout=5)
    
    # Verify response received
    assert response is not None
    assert response["request_id"] == request_id
    assert response["status"] == "success"
    assert response["result"]["message"] == "test response"
    
    # Cleanup
    await backend_redis.delete(f"response:{request_id}")


@pytest.mark.asyncio
async def test_response_timeout():
    """Test that backend times out correctly when agent doesn't respond."""
    
    backend_redis = await get_redis()
    if not backend_redis:
        pytest.skip("Redis not available for integration test")
    
    # Generate request ID that won't have a response
    request_id = str(uuid.uuid4())
    
    # Poll for response (should timeout)
    response = await get_response(request_id, timeout=1)
    
    # Verify no response received
    assert response is None


@pytest.mark.asyncio
async def test_response_ttl_expiration():
    """Test that responses expire after TTL."""
    
    backend_redis = await get_redis()
    agent_redis = await agent_get_redis()
    
    if not backend_redis or not agent_redis:
        pytest.skip("Redis not available for integration test")
    
    request_id = str(uuid.uuid4())
    
    # Agent sends response with short TTL
    test_response = {
        "request_id": request_id,
        "status": "success"
    }
    
    await agent_redis.setex(
        f"response:{request_id}",
        1,  # 1 second TTL
        json.dumps(test_response)
    )
    
    # Immediately get response (should succeed)
    response = await get_response(request_id, timeout=2)
    assert response is not None
    
    # Wait for TTL to expire
    await asyncio.sleep(2)
    
    # Try to get response again (should fail)
    response = await get_response(request_id, timeout=1)
    assert response is None


@pytest.mark.asyncio
async def test_command_queue_mechanism():
    """Test that commands are properly enqueued."""
    
    backend_redis = await get_redis()
    if not backend_redis:
        pytest.skip("Redis not available for integration test")
    
    command_queue = "test_command_queue"
    command = {
        "request_id": str(uuid.uuid4()),
        "command": "test",
        "parameters": {},
        "timestamp": 1234567890.0
    }
    
    # Enqueue command
    success = await enqueue_command(command, command_queue)
    assert success is True
    
    # Verify command in queue
    result = await backend_redis.brpop(command_queue, timeout=2)
    assert result is not None
    queue_name, command_json = result
    assert queue_name == command_queue
    
    # Parse and verify command
    queued_command = json.loads(command_json)
    assert queued_command["request_id"] == command["request_id"]
    assert queued_command["command"] == command["command"]
    
    # Cleanup
    await backend_redis.delete(command_queue)

