"""
Contract tests for unified WebSocket manager message envelope.

Ensures broadcast messages have legacy-compatible shape: type, resource (optional), data.
"""

import pytest
from backend.api.websocket.unified_manager import _envelope_to_legacy_dict
from backend.core.websocket_messages import (
    WebSocketEnvelope,
    WebSocketMessageType,
    WebSocketResource,
    create_health_update,
    create_agent_state_update,
)


def test_envelope_to_legacy_dict_from_dict():
    """Plain dict is returned as-is (with no enum conversion)."""
    msg = {"type": "data_update", "resource": "signal", "data": {"signal": "BUY"}}
    out = _envelope_to_legacy_dict(msg)
    assert out["type"] == "data_update"
    assert out["resource"] == "signal"
    assert out["data"] == {"signal": "BUY"}


def test_envelope_to_legacy_dict_from_websocket_envelope():
    """WebSocketEnvelope is converted to dict with string type/resource."""
    env = WebSocketEnvelope(
        type=WebSocketMessageType.DATA_UPDATE,
        resource=WebSocketResource.SIGNAL,
        data={"signal": "HOLD"},
    )
    out = _envelope_to_legacy_dict(env)
    assert out["type"] == "data_update"
    assert out["resource"] == "signal"
    assert out["data"] == {"signal": "HOLD"}


def test_create_health_update_produces_legacy_shape():
    """create_health_update yields envelope that converts to type/system_update, resource/health, data."""
    health_data = {
        "status": "healthy",
        "health_score": 0.95,
        "trading_ready": True,
        "degradation_reasons": [],
    }
    env = create_health_update(health_data)
    out = _envelope_to_legacy_dict(env)
    assert out["type"] == "system_update"
    assert out["resource"] == "health"
    assert out["data"]["status"] == "healthy"
    assert out["data"]["trading_ready"] is True


def test_create_agent_state_update_produces_legacy_shape():
    """create_agent_state_update yields envelope with type agent_update and data."""
    state_data = {"state": "MONITORING", "timestamp": "2025-01-01T00:00:00Z", "reason": ""}
    env = create_agent_state_update(state_data)
    out = _envelope_to_legacy_dict(env)
    assert out["type"] == "agent_update"
    assert out["data"]["state"] == "MONITORING"
    assert out.get("resource") == "agent"


def test_apply_frontend_wire_metadata_stamps_schema_and_time():
    """Dashboard-bound messages get schema_version and server timestamps."""
    from backend.api.websocket.unified_manager import UnifiedWebSocketManager

    mgr = UnifiedWebSocketManager.__new__(UnifiedWebSocketManager)
    msg: dict = {"type": "data_update", "resource": "signal", "data": {"x": 1}}
    UnifiedWebSocketManager._apply_frontend_wire_metadata(mgr, msg)
    sv = msg.get("schema_version")
    assert isinstance(sv, int) and sv >= 1
    assert "server_timestamp" in msg
    assert "server_timestamp_ms" in msg
