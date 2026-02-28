"""
Communication logger for tracking all inter-service communication.

Provides structured logging for WebSocket messages, command requests/responses,
and data flows between backend, frontend, and agent services.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union
import structlog

from backend.core.config import settings

# Communication log file path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_ROOT = PROJECT_ROOT / "logs"
COMMUNICATION_LOG_FILE = LOGS_ROOT / "backend" / "communication.log"

# Default configuration values
DEFAULT_MAX_PAYLOAD_SIZE = 10 * 1024  # 10KB
DEFAULT_SENSITIVE_FIELDS = {"password", "token", "api_key", "secret"}

_logger: Optional[logging.Logger] = None
_struct_logger: Optional[structlog.BoundLoggerBase] = None


def _get_config_value(name: str, default: Any) -> Any:
    """Get configuration value from settings or use default."""
    return getattr(settings, name, default)


def _sanitize_payload(payload: Any, sensitive_fields: set = None) -> Any:
    """Sanitize payload by removing or masking sensitive fields."""
    if sensitive_fields is None:
        sensitive_fields = _get_config_value("COMMUNICATION_SENSITIVE_FIELDS", DEFAULT_SENSITIVE_FIELDS)

    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            if key.lower() in sensitive_fields:
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = _sanitize_payload(value, sensitive_fields)
        return sanitized
    elif isinstance(payload, list):
        return [_sanitize_payload(item, sensitive_fields) for item in payload]
    else:
        return payload


def _truncate_payload(payload: Any, max_size: int = None) -> Any:
    """Truncate payload if it exceeds maximum size."""
    if max_size is None:
        max_size = _get_config_value("COMMUNICATION_MAX_PAYLOAD_SIZE", DEFAULT_MAX_PAYLOAD_SIZE)

    payload_str = json.dumps(payload, default=str)
    if len(payload_str) > max_size:
        # Truncate and add indicator
        truncated = payload_str[:max_size - 50] + "...[TRUNCATED]"
        return {"truncated": True, "size": len(payload_str), "content": truncated}

    return payload


def _get_payload_summary(payload: Any) -> Dict[str, Any]:
    """Generate payload summary for logging."""
    if payload is None:
        return {"type": "null", "size_bytes": 0}

    sanitized = _sanitize_payload(payload)
    truncated = _truncate_payload(sanitized)

    summary = {
        "type": type(payload).__name__,
        "size_bytes": len(json.dumps(payload, default=str))
    }

    # Add structure information for complex types
    if isinstance(payload, dict):
        summary["keys"] = list(payload.keys())
        summary["key_count"] = len(payload)
    elif isinstance(payload, list):
        summary["length"] = len(payload)
        if payload and isinstance(payload[0], dict):
            summary["item_keys"] = list(payload[0].keys()) if payload[0] else []

    summary["payload"] = truncated
    return summary


def _ensure_log_directory() -> None:
    """Ensure communication log directory exists."""
    COMMUNICATION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def _get_logger() -> structlog.BoundLoggerBase:
    """Get or create the communication logger."""
    global _logger, _struct_logger

    if _struct_logger is not None:
        return _struct_logger

    # Create dedicated logger for communication
    _logger = logging.getLogger("communication")
    _logger.setLevel(logging.INFO)

    # Create log directory
    _ensure_log_directory()

    # Add file handler for communication logs
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        COMMUNICATION_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )

    # Use JSON formatter for structured logging
    formatter = logging.Formatter(
        '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": %(message)s}',
        datefmt="%Y-%m-%dT%H:%M:%SZ"
    )
    formatter.converter = lambda x: datetime.fromtimestamp(x, tz=timezone.utc).timetuple()
    file_handler.setFormatter(formatter)

    _logger.addHandler(file_handler)
    _logger.propagate = False  # Don't propagate to root logger

    # Use structlog.wrap_logger to create a bound logger without overwriting global config
    _struct_logger = structlog.wrap_logger(
        _logger,
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
    )
    return _struct_logger


def log_communication(
    direction: str,  # "inbound" | "outbound"
    protocol: str,  # "websocket" | "redis" | "http"
    message_type: str,  # "data_update" | "command" | "response" | "event"
    resource: Optional[str] = None,  # "signal" | "portfolio" | "trade" | etc.
    correlation_id: Optional[str] = None,
    target: Optional[str] = None,  # "frontend" | "agent" | "backend"
    connection_id: Optional[str] = None,
    payload: Any = None,
    latency_ms: Optional[float] = None,
    error: Optional[str] = None,
    **extra_fields
) -> None:
    """Log inter-service communication event.

    Args:
        direction: Direction of communication ("inbound" | "outbound")
        protocol: Communication protocol ("websocket" | "redis" | "http")
        message_type: Type of message ("data_update" | "command" | "response" | "event")
        resource: Resource type (e.g., "signal", "portfolio", "trade")
        correlation_id: Correlation ID for request/response tracking
        target: Target service ("frontend" | "agent" | "backend")
        connection_id: Connection identifier
        payload: Message payload to log
        latency_ms: Latency in milliseconds
        error: Error message if applicable
        **extra_fields: Additional fields to include in log
    """
    # Check if communication logging is enabled
    if not _get_config_value("ENABLE_COMMUNICATION_LOGGING", True):
        return

    logger = _get_logger()

    # Build log entry
    log_entry = {
        "service": "backend",
        "direction": direction,
        "protocol": protocol,
        "message_type": message_type,
        "resource": resource,
        "correlation_id": correlation_id,
        "target": target,
        "connection_id": connection_id,
    }

    # Add optional fields
    if latency_ms is not None:
        log_entry["latency_ms"] = round(latency_ms, 2)

    if error:
        log_entry["error"] = error

    # Add payload summary if payload provided
    if payload is not None:
        log_entry["payload_summary"] = _get_payload_summary(payload)

    # Add extra fields
    log_entry.update(extra_fields)

    # Log the entry
    logger.info("communication_event", **log_entry)


def log_websocket_message(
    direction: str,
    message_type: str,
    resource: Optional[str] = None,
    correlation_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    payload: Any = None,
    target: str = "frontend"
) -> None:
    """Log WebSocket message communication."""
    log_communication(
        direction=direction,
        protocol="websocket",
        message_type=message_type,
        resource=resource,
        correlation_id=correlation_id,
        connection_id=connection_id,
        payload=payload,
        target=target
    )


def log_agent_command(
    direction: str,
    command: str,
    correlation_id: str,
    payload: Any = None,
    latency_ms: Optional[float] = None,
    error: Optional[str] = None
) -> None:
    """Log agent command communication."""
    log_communication(
        direction=direction,
        protocol="websocket",  # Primary protocol, fallback to redis
        message_type="command" if direction == "outbound" else "response",
        resource=command,
        correlation_id=correlation_id,
        target="agent",
        payload=payload,
        latency_ms=latency_ms,
        error=error
    )


def log_frontend_command(
    direction: str,
    command: str,
    correlation_id: str,
    payload: Any = None,
    latency_ms: Optional[float] = None,
    error: Optional[str] = None
) -> None:
    """Log frontend command communication."""
    log_communication(
        direction=direction,
        protocol="websocket",
        message_type="command" if direction == "inbound" else "response",
        resource=command,
        correlation_id=correlation_id,
        target="frontend",
        payload=payload,
        latency_ms=latency_ms,
        error=error
    )


def log_data_flow(
    source: str,
    destination: str,
    data_type: str,
    data_id: Optional[str] = None,
    payload: Any = None,
    correlation_id: Optional[str] = None
) -> None:
    """Log data flow between services."""
    log_communication(
        direction="outbound",
        protocol="websocket",
        message_type="data_flow",
        resource=data_type,
        correlation_id=correlation_id,
        target=destination,
        payload=payload,
        source=source,
        data_id=data_id
    )


# Utility functions for correlation ID generation
def generate_correlation_id(prefix: str = "corr") -> str:
    """Generate a unique correlation ID."""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def extract_correlation_id(message: Dict[str, Any]) -> Optional[str]:
    """Extract correlation ID from message."""
    return message.get("correlation_id") or message.get("request_id")