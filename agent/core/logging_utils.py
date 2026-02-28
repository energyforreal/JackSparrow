"""Logging configuration utilities for the agent service."""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import uuid

import structlog

from agent.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_ROOT = Path(os.environ.get("LOGS_ROOT", str(PROJECT_ROOT / "logs")))
LOG_FILE = LOGS_ROOT / "agent.log"
ARCHIVE_DIR = LOGS_ROOT / "archive" / "agent"

_SESSION_ID: Optional[str] = None


def _add_logger_name(
    logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Ensure every event captures the logger name regardless of structlog version."""
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        event_dict["logger"] = record.name
    else:
        event_dict["logger"] = logger.name
    return event_dict


def _get_log_level() -> int:
    level_name = (settings.agent_log_level or settings.log_level or "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _archive_previous_log() -> Optional[Path]:
    if not LOG_FILE.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = ARCHIVE_DIR / f"{timestamp}-agent.log"
    try:
        LOG_FILE.replace(archive_path)
    except OSError:
        # If replacement fails, leave the existing file in place to avoid losing logs.
        return None
    return archive_path


def configure_logging(force: bool = False) -> str:
    """Configure structured logging for the agent.

    Args:
        force: Reconfigure even if logging has already been configured.

    Returns:
        The session identifier used for this logging run.
    """
    global _SESSION_ID
    if _SESSION_ID and not force:
        return _SESSION_ID

    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    _archive_previous_log()

    level = _get_log_level()

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
        ],
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logging.basicConfig(
        level=level,
        handlers=[file_handler, console_handler],
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    session_id = os.environ.get("LOG_SESSION_ID") or uuid.uuid4().hex
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service="agent",
        environment=getattr(settings, "environment", "local"),
        session_id=session_id,
    )

    _SESSION_ID = session_id
    return session_id


def _build_log_context(
    message: str,
    component: Optional[str],
    request_id: Optional[str],
    extra: Dict[str, Any],
) -> Dict[str, Any]:
    """Compose shared log context for agent logs."""
    return {
        "service": "agent",
        "message": message,
        "component": component or extra.get("component"),
        "request_id": request_id or extra.get("request_id"),
        **extra,
    }


def log_error_with_context(
    event: str,
    error: Optional[Exception] = None,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
    message: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Log an error with standardized agent context.

    Args:
        event: Event identifier (logged under the ``event`` field).
        error: Exception object to attach (optional).
        component: Component name emitting the log.
        request_id: Request correlation identifier.
        message: Human-friendly message override. Defaults to ``event``.
        **kwargs: Additional structured fields.
    """
    logger = structlog.get_logger()
    explicit_message = message or kwargs.pop("message", None)
    final_message = explicit_message or event
    log_kwargs = _build_log_context(final_message, component, request_id, kwargs)

    if error:
        log_kwargs.update(
            {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "exc_info": True,
            }
        )

    logger.error(message, **log_kwargs)


def log_warning_with_context(
    event: str,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
    message: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Log a warning with standardized agent context."""
    logger = structlog.get_logger()
    explicit_message = message or kwargs.pop("message", None)
    final_message = explicit_message or event
    log_kwargs = _build_log_context(final_message, component, request_id, kwargs)
    logger.warning(final_message, **log_kwargs)


def log_exception(
    event: str,
    error: Optional[Exception] = None,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
    message: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Convenience helper for error logs that always include exception info."""
    log_error_with_context(
        event,
        error=error,
        component=component,
        request_id=request_id,
        message=message,
        **kwargs,
    )

