"""
Event utilities for trading agent.

Provides helper functions for event handling.
"""

import json
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

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
        "timestamp": datetime.utcnow().isoformat()
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
    
    # Handle datetime strings
    if "timestamp" in event_dict:
        if isinstance(event_dict["timestamp"], str):
            event_dict["timestamp"] = datetime.fromisoformat(event_dict["timestamp"])
    
    # Handle nested payload timestamps
    if "payload" in event_dict and isinstance(event_dict["payload"], dict):
        for key, value in event_dict["payload"].items():
            if isinstance(value, str) and "timestamp" in key.lower():
                try:
                    event_dict["payload"][key] = datetime.fromisoformat(value)
                except (ValueError, TypeError):
                    pass
    
    return event_class(**event_dict)

