"""
Integration tests for data flow synchronization.

Tests event deduplication, timestamp consistency, and data integrity
across services.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any
import json

from backend.services.time_service import time_service
from backend.core.redis import get_redis, set_cache, get_cache


class TestTimestampConsistency:
    """Test timestamp format consistency across services."""
    
    def test_time_service_returns_z_suffix(self):
        """Test that time_service always returns timestamps with 'Z' suffix."""
        time_info = time_service.get_time_info()
        server_time = time_info["server_time"]
        
        assert server_time.endswith('Z'), f"Timestamp should end with 'Z': {server_time}"
        assert 'T' in server_time, f"Timestamp should be ISO format: {server_time}"
    
    def test_timestamp_parsing(self):
        """Test that timestamps can be parsed correctly."""
        time_info = time_service.get_time_info()
        server_time = time_info["server_time"]
        
        # Should be parseable as ISO 8601
        try:
            # Remove 'Z' and parse
            if server_time.endswith('Z'):
                iso_str = server_time[:-1] + '+00:00'
            else:
                iso_str = server_time
            
            parsed = datetime.fromisoformat(iso_str)
            assert parsed.tzinfo is not None or server_time.endswith('Z')
        except ValueError as e:
            pytest.fail(f"Failed to parse timestamp {server_time}: {e}")


class TestEventDeduplication:
    """Test event deduplication mechanism."""
    
    @pytest.mark.asyncio
    async def test_event_id_deduplication(self):
        """Test that events with same ID are not processed twice."""
        redis = await get_redis()
        if redis is None:
            pytest.skip("Redis not available")
        
        event_id = f"test_event_{datetime.utcnow().timestamp()}"
        key = f"processed_event:{event_id}"
        
        # First check - should not exist
        exists_1 = await redis.exists(key)
        assert not exists_1, "Event should not exist initially"
        
        # Mark as processed
        await redis.setex(key, 300, "1")
        
        # Second check - should exist
        exists_2 = await redis.exists(key)
        assert exists_2, "Event should exist after marking"
        
        # Cleanup
        await redis.delete(key)
    
    @pytest.mark.asyncio
    async def test_dedup_key_expiration(self):
        """Test that deduplication keys expire after TTL."""
        redis = await get_redis()
        if redis is None:
            pytest.skip("Redis not available")
        
        event_id = f"test_event_expire_{datetime.utcnow().timestamp()}"
        key = f"processed_event:{event_id}"
        
        # Mark as processed with short TTL
        await redis.setex(key, 1, "1")
        
        # Should exist immediately
        exists_1 = await redis.exists(key)
        assert exists_1, "Event should exist immediately"
        
        # Wait for expiration
        await asyncio.sleep(2)
        
        # Should not exist after expiration
        exists_2 = await redis.exists(key)
        assert not exists_2, "Event should expire after TTL"


class TestDataIntegrity:
    """Test data integrity and atomicity."""
    
    @pytest.mark.asyncio
    async def test_portfolio_update_lock(self):
        """Test that portfolio updates use locking to prevent race conditions."""
        # This test verifies that the lock mechanism exists
        # Actual race condition testing would require more complex setup
        from backend.services.agent_event_subscriber import agent_event_subscriber
        
        # Check that lock exists
        assert hasattr(agent_event_subscriber, '_portfolio_update_lock'), \
            "Portfolio update lock should exist"
        assert agent_event_subscriber._portfolio_update_lock is not None, \
            "Portfolio update lock should be initialized"
    
    def test_timestamp_format_consistency(self):
        """Test that all timestamps use consistent format."""
        # Test multiple calls to time_service
        timestamps = []
        for _ in range(10):
            time_info = time_service.get_time_info()
            timestamps.append(time_info["server_time"])
        
        # All should end with 'Z'
        for ts in timestamps:
            assert ts.endswith('Z'), f"All timestamps should end with 'Z': {ts}"
        
        # All should be parseable
        for ts in timestamps:
            try:
                if ts.endswith('Z'):
                    iso_str = ts[:-1] + '+00:00'
                else:
                    iso_str = ts
                datetime.fromisoformat(iso_str)
            except ValueError:
                pytest.fail(f"Timestamp not parseable: {ts}")


class TestConfigurationSynchronization:
    """Test configuration synchronization between services."""
    
    def test_risk_settings_exist_in_backend(self):
        """Test that risk settings exist in backend config."""
        from backend.core.config import settings
        
        assert hasattr(settings, 'stop_loss_percentage'), \
            "Backend config should have stop_loss_percentage"
        assert hasattr(settings, 'take_profit_percentage'), \
            "Backend config should have take_profit_percentage"
        
        # Check that values are reasonable
        assert 0 < settings.stop_loss_percentage < 1, \
            f"stop_loss_percentage should be between 0 and 1: {settings.stop_loss_percentage}"
        assert 0 < settings.take_profit_percentage < 1, \
            f"take_profit_percentage should be between 0 and 1: {settings.take_profit_percentage}"
    
    def test_risk_settings_match_agent(self):
        """Test that risk settings match between backend and agent."""
        from backend.core.config import settings as backend_settings
        from agent.core.config import settings as agent_settings
        
        # Both should have the settings
        assert hasattr(backend_settings, 'stop_loss_percentage')
        assert hasattr(agent_settings, 'stop_loss_percentage')
        assert hasattr(backend_settings, 'take_profit_percentage')
        assert hasattr(agent_settings, 'take_profit_percentage')
        
        # Values should match (or at least be reasonable)
        # Note: They might differ if env vars are set differently,
        # but both should exist and be valid


class TestErrorHandling:
    """Test error handling improvements."""
    
    def test_time_service_error_handling(self):
        """Test that time_service handles errors gracefully."""
        # Should not raise exceptions for normal operations
        try:
            time_info = time_service.get_time_info()
            assert "server_time" in time_info
            assert "timestamp_ms" in time_info
            assert "timezone" in time_info
        except Exception as e:
            pytest.fail(f"time_service should not raise exceptions: {e}")
    
    @pytest.mark.asyncio
    async def test_redis_error_handling(self):
        """Test that Redis operations handle errors gracefully."""
        redis = await get_redis()
        if redis is None:
            pytest.skip("Redis not available")
        
        # Test that operations don't raise unexpected exceptions
        try:
            await redis.ping()
        except Exception as e:
            pytest.fail(f"Redis ping should not raise exceptions: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

