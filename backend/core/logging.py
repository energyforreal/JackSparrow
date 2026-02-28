"""Logging configuration utilities for the backend service."""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import uuid

import structlog

from backend.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_ROOT = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_ROOT / "backend" / "backend.log"
ERROR_LOG_FILE = LOGS_ROOT / "backend" / "errors.log"
WARNING_LOG_FILE = LOGS_ROOT / "backend" / "warnings.log"
ARCHIVE_DIR = LOGS_ROOT / "archive" / "backend"

_SESSION_ID: Optional[str] = None


def _add_logger_name(
    logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Ensure every event includes the emitting logger's name."""
    record = event_dict.get("_record")
    event_dict["logger"] = record.name if record else logger.name
    return event_dict


def _get_log_level() -> int:
    """Get log level from settings."""
    level_name = (settings.backend_log_level or settings.log_level or "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _archive_previous_log(log_file: Path) -> Optional[Path]:
    """Archive a log file if it exists."""
    if not log_file.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = ARCHIVE_DIR / f"{timestamp}-{log_file.name}"
    try:
        log_file.replace(archive_path)
    except OSError:
        return None
    return archive_path


def _archive_previous_logs() -> Dict[str, Optional[Path]]:
    """Archive all previous log files."""
    archived = {}
    log_files = [LOG_FILE, ERROR_LOG_FILE, WARNING_LOG_FILE]
    for log_file in log_files:
        if log_file.exists():
            archived[log_file.name] = _archive_previous_log(log_file)
    return archived


def configure_logging(force: bool = False) -> str:
    """Configure structured logging for the backend.
    
    Args:
        force: Reconfigure even if logging has already been configured.
        
    Returns:
        The session identifier used for this logging run.
    """
    global _SESSION_ID
    if _SESSION_ID and not force:
        return _SESSION_ID
    
    # Create log directories
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    (LOGS_ROOT / "backend").mkdir(parents=True, exist_ok=True)
    
    # Archive previous logs
    archived_logs = _archive_previous_logs()
    
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
    
    # Main log file handler
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    
    # Error log file handler (ERROR and CRITICAL only)
    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding="utf-8",
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(lambda record: record.levelno >= logging.ERROR)
    
    # Warning log file handler (WARNING only)
    warning_handler = logging.handlers.RotatingFileHandler(
        WARNING_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,
        encoding="utf-8",
    )
    warning_handler.setFormatter(formatter)
    warning_handler.setLevel(logging.WARNING)
    warning_handler.addFilter(lambda record: record.levelno == logging.WARNING)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, error_handler, warning_handler, console_handler],
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
        service="backend",
        environment=getattr(settings, "environment", "local"),
        session_id=session_id,
    )
    
    _SESSION_ID = session_id
    
    # Log startup
    try:
        logger = structlog.get_logger()
        logger.info(
            "system.startup",
            service="backend",
            session_id=session_id,
            environment=getattr(settings, "environment", "local"),
            archived_logs=len([v for v in archived_logs.values() if v is not None]),
            log_files={
                "main": str(LOG_FILE),
                "errors": str(ERROR_LOG_FILE),
                "warnings": str(WARNING_LOG_FILE),
            }
        )
    except Exception:
        pass
    
    return session_id


def log_error_with_context(
    message: str,
    error: Optional[Exception] = None,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
    **kwargs
) -> None:
    """Log an error with standardized context.
    
    Args:
        message: Error message
        error: Exception object (optional)
        component: Component name (optional)
        request_id: Request ID for request tracking (optional)
        **kwargs: Additional context fields
    """
    # Use stdlib logger to avoid structlog config conflicts (e.g. from communication_logger)
    _log = logging.getLogger("backend.errors")
    error_type = type(error).__name__ if error else "UnknownError"
    extra = {
        "service": "backend",
        "component": component or kwargs.get("component"),
        "request_id": request_id or kwargs.get("request_id"),
        "error_type": error_type,
        **{k: v for k, v in kwargs.items() if k not in ("exc_info", "stack_info")},
    }
    if error:
        extra["error_message"] = str(error)
    _log.error(
        message,
        exc_info=error is not None,
        extra=extra,
    )


def get_session_id() -> Optional[str]:
    """Get current session ID."""
    return _SESSION_ID

