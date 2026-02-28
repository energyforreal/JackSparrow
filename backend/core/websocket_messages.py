"""
Simplified WebSocket message handling with unified envelope format.

This module provides a standardized way to create and send WebSocket messages,
reducing complexity from 10+ message types to 3-4 core types.
"""

from typing import Dict, Any, Optional, Union
from datetime import datetime, timezone
import uuid
from dataclasses import dataclass, asdict

from backend.core.enums import WebSocketMessageType, WebSocketResource


@dataclass
class WebSocketEnvelope:
    """Standardized WebSocket message envelope.

    All WebSocket messages follow this format for consistency.
    """
    type: WebSocketMessageType
    resource: Optional[WebSocketResource] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: str = None
    sequence: Optional[int] = None
    source: str = "system"
    request_id: Optional[str] = None  # For request-response correlation

    def __post_init__(self):
        """Set default timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Remove None values for cleaner JSON
        return {k: v for k, v in result.items() if v is not None}


class WebSocketMessageBuilder:
    """Builder for creating standardized WebSocket messages."""

    _sequence_counter = 0

    @classmethod
    def _get_next_sequence(cls) -> int:
        """Get next sequence number for message ordering."""
        cls._sequence_counter += 1
        return cls._sequence_counter

    @classmethod
    def data_update(
        cls,
        resource: WebSocketResource,
        data: Dict[str, Any],
        source: str = "system"
    ) -> WebSocketEnvelope:
        """Create a data update message.

        Replaces: signal_update, portfolio_update, trade_executed, market_tick, etc.
        """
        return WebSocketEnvelope(
            type=WebSocketMessageType.DATA_UPDATE,
            resource=resource,
            data=data,
            sequence=cls._get_next_sequence(),
            source=source
        )

    @classmethod
    def agent_update(
        cls,
        data: Dict[str, Any],
        source: str = "agent"
    ) -> WebSocketEnvelope:
        """Create an agent update message.

        Replaces: agent_state messages
        """
        return WebSocketEnvelope(
            type=WebSocketMessageType.AGENT_UPDATE,
            resource=WebSocketResource.AGENT,
            data=data,
            sequence=cls._get_next_sequence(),
            source=source
        )

    @classmethod
    def system_update(
        cls,
        resource: WebSocketResource,
        data: Dict[str, Any],
        source: str = "system"
    ) -> WebSocketEnvelope:
        """Create a system update message.

        Replaces: health_update, time_sync, performance_update
        """
        return WebSocketEnvelope(
            type=WebSocketMessageType.SYSTEM_UPDATE,
            resource=resource,
            data=data,
            sequence=cls._get_next_sequence(),
            source=source
        )

    @classmethod
    def response(
        cls,
        request_id: str,
        data: Dict[str, Any],
        source: str = "system"
    ) -> WebSocketEnvelope:
        """Create a response message for request-response pattern."""
        return WebSocketEnvelope(
            type=WebSocketMessageType.RESPONSE,
            data=data,
            sequence=cls._get_next_sequence(),
            source=source,
            request_id=request_id
        )

    @classmethod
    def error(
        cls,
        error_message: str,
        error_code: str = "UNKNOWN_ERROR",
        request_id: Optional[str] = None,
        source: str = "system"
    ) -> WebSocketEnvelope:
        """Create an error message."""
        return WebSocketEnvelope(
            type=WebSocketMessageType.ERROR,
            data={
                "error": {
                    "code": error_code,
                    "message": error_message,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            },
            sequence=cls._get_next_sequence(),
            source=source,
            request_id=request_id
        )


# Convenience functions for common message types
def create_signal_update(signal_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a trading signal update message."""
    return WebSocketMessageBuilder.data_update(WebSocketResource.SIGNAL, signal_data, "agent")


def create_portfolio_update(portfolio_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a portfolio update message."""
    return WebSocketMessageBuilder.data_update(WebSocketResource.PORTFOLIO, portfolio_data, "system")


def create_trade_update(trade_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a trade execution update message."""
    return WebSocketMessageBuilder.data_update(WebSocketResource.TRADE, trade_data, "system")


def create_market_update(market_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a market data update message."""
    return WebSocketMessageBuilder.data_update(WebSocketResource.MARKET, market_data, "system")


def create_health_update(health_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a system health update message."""
    return WebSocketMessageBuilder.system_update(WebSocketResource.HEALTH, health_data, "system")


def create_time_sync(time_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a time synchronization message."""
    return WebSocketMessageBuilder.system_update(WebSocketResource.TIME, time_data, "system")


def create_agent_state_update(state_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create an agent state update message."""
    return WebSocketMessageBuilder.agent_update(state_data, "agent")


def create_model_update(model_data: Dict[str, Any]) -> WebSocketEnvelope:
    """Create a model prediction update message."""
    return WebSocketMessageBuilder.data_update(WebSocketResource.MODEL, model_data, "agent")