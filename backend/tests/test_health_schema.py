"""
Contract tests for health payload schema.

Ensures HealthResponse and health payload include status, trading_ready,
degradation_reasons so frontend and WebSocket consumers can rely on a stable shape.
"""

import pytest
from backend.api.models.responses import HealthResponse, HealthServiceStatus


def test_health_response_model_has_trading_ready_and_status():
    """HealthResponse must accept status, trading_ready, degradation_reasons."""
    payload = {
        "status": "healthy",
        "health_score": 0.95,
        "services": {
            "database": {"status": "up"},
            "redis": {"status": "up"},
            "agent": {"status": "up"},
            "feature_server": {"status": "up"},
            "model_nodes": {"status": "up"},
            "delta_exchange": {"status": "up"},
            "reasoning_engine": {"status": "up"},
        },
        "degradation_reasons": [],
        "trading_ready": True,
        "timestamp": "2025-01-01T00:00:00Z",
    }
    resp = HealthResponse(**payload)
    assert resp.status == "healthy"
    assert resp.health_score == 0.95
    assert resp.trading_ready is True
    assert resp.degradation_reasons == []


def test_health_response_trading_ready_optional():
    """trading_ready is optional for backward compatibility."""
    payload = {
        "status": "degraded",
        "health_score": 0.5,
        "services": {"database": {"status": "up"}, "redis": {"status": "down"}},
        "degradation_reasons": ["Redis is down"],
        "timestamp": "2025-01-01T00:00:00Z",
    }
    resp = HealthResponse(**payload)
    assert resp.trading_ready is None
    assert resp.status == "degraded"
