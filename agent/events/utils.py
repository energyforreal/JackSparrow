"""
Event utilities for trading agent.

Provides helper functions for event handling.
"""

import json
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from agent.core.decision_timestamp import parse_utc_datetime
from agent.events.schemas import BaseEvent


def generate_event_id() -> str:
    """Generate unique event ID."""
    return str(uuid.uuid4())


def create_correlation_context(parent_event_id: Optional[str] = None) -> Dict[str, Any]:
    """Create correlation context for event chains.
    
    Args:
        parent_event_id: Optional parent event ID to correlate with
        
    Returns:
        Dictionary with correlation context
    """
    context = {
        "correlation_id": parent_event_id or generate_event_id(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if parent_event_id:
        context["parent_event_id"] = parent_event_id
    
    return context


def serialize_event(event: BaseEvent) -> bytes:
    """Serialize event to bytes.
    
    Args:
        event: Event to serialize
        
    Returns:
        Serialized event as bytes
    """
    return json.dumps(event.dict(), default=str).encode("utf-8")


def deserialize_event(data: bytes, event_class: type = BaseEvent) -> BaseEvent:
    """Deserialize event from bytes.
    
    Args:
        data: Serialized event data
        event_class: Event class to deserialize to
        
    Returns:
        Deserialized event instance
    """
    event_dict = json.loads(data.decode("utf-8"))
    
    # Handle datetime strings (naive ISO → UTC for Windows/IST hosts)
    if "timestamp" in event_dict:
        parsed = parse_utc_datetime(event_dict["timestamp"])
        if parsed is not None:
            event_dict["timestamp"] = parsed

    if "payload" in event_dict and isinstance(event_dict["payload"], dict):
        parsed_ts = parse_utc_datetime(event_dict["payload"].get("timestamp"))
        if parsed_ts is not None:
            event_dict["payload"]["timestamp"] = parsed_ts
    
    return event_class(**event_dict)

