"""Global exception handlers for unhandled exceptions.

Provides centralized exception handling for synchronous, asynchronous, and thread-based
code to ensure all unhandled exceptions are properly logged with full context.
"""

from __future__ import annotations

import sys
import asyncio
import threading
import traceback
from typing import Optional, Any
import structlog

from agent.core.logging_utils import log_exception, get_session_id

logger = structlog.get_logger()


def _format_exception_info(exc_type, exc_value, exc_traceback) -> dict:
    """Format exception information for logging.
    
    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_traceback: Exception traceback
        
    Returns:
        Dictionary with formatted exception information
    """
    if exc_type is None or exc_value is None or exc_traceback is None:
        return {}
    
    return {
        "error_type": exc_type.__name__,
        "error_message": str(exc_value),
        "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
    }


def _sync_exception_handler(exc_type, exc_value, exc_traceback, thread=None):
    """Handle unhandled synchronous exceptions.
    
    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_traceback: Exception traceback
        thread: Thread that raised the exception (if any)
    """
    # Ignore KeyboardInterrupt to allow normal shutdown
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    exception_info = _format_exception_info(exc_type, exc_value, exc_traceback)
    
    log_context = {
        "service": "agent",
        "component": "global_exception_handler",
        "exception_type": "synchronous",
        "session_id": get_session_id(),
    }
    
    if thread:
        log_context["thread_name"] = thread.name
        log_context["thread_id"] = thread.ident
    
    log_context.update(exception_info)
    
    logger.error(
        "unhandled_sync_exception",
        exc_info=(exc_type, exc_value, exc_traceback),
        **log_context
    )
    
    # Call default exception handler for additional output
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _async_exception_handler(loop: asyncio.AbstractEventLoop, context: dict):
    """Handle unhandled asynchronous exceptions.
    
    Args:
        loop: Event loop where the exception occurred
        context: Exception context dictionary
    """
    exception = context.get("exception")
    message = context.get("message", "Unhandled async exception")
    
    log_context = {
        "service": "agent",
        "component": "global_exception_handler",
        "exception_type": "asynchronous",
        "session_id": get_session_id(),
        "task": context.get("task"),
        "future": str(context.get("future")),
    }
    
    if exception:
        log_exception(
            exception,
            message=message,
            component="async_task",
            **log_context
        )
    else:
        logger.error(
            "unhandled_async_exception",
            message=message,
            context=context,
            **log_context
        )


def _thread_exception_handler(args):
    """Handle unhandled thread exceptions.
    
    Args:
        args: Exception arguments (exc_type, exc_value, exc_traceback, thread)
    """
    exc_type, exc_value, exc_traceback, thread = args
    
    # Ignore KeyboardInterrupt to allow normal shutdown
    if exc_type is KeyboardInterrupt:
        return
    
    exception_info = _format_exception_info(exc_type, exc_value, exc_traceback)
    
    log_context = {
        "service": "agent",
        "component": "global_exception_handler",
        "exception_type": "thread",
        "session_id": get_session_id(),
        "thread_name": thread.name if thread else "unknown",
        "thread_id": thread.ident if thread else None,
    }
    
    log_context.update(exception_info)
    
    logger.error(
        "unhandled_thread_exception",
        exc_info=(exc_type, exc_value, exc_traceback),
        **log_context
    )


def setup_global_exception_handlers():
    """Set up global exception handlers for all unhandled exceptions.
    
    This function should be called once during application startup to ensure
    all unhandled exceptions are properly logged.
    """
    # Set up synchronous exception handler
    sys.excepthook = _sync_exception_handler
    
    # Set up async exception handler
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop exists yet, will be set up when loop is created
            pass
    
    if loop and not loop.is_closed():
        loop.set_exception_handler(_async_exception_handler)
    
    # Set up thread exception handler (Python 3.8+)
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_exception_handler
    
    logger.info(
        "global_exception_handlers_installed",
        service="agent",
        session_id=get_session_id(),
        handlers={
            "sync": "installed",
            "async": "installed" if loop and not loop.is_closed() else "pending",
            "thread": "installed" if hasattr(threading, "excepthook") else "not_available",
        }
    )


def install_async_exception_handler(loop: asyncio.AbstractEventLoop):
    """Install async exception handler on an existing event loop.
    
    Args:
        loop: Event loop to install handler on
    """
    loop.set_exception_handler(_async_exception_handler)
    logger.debug(
        "async_exception_handler_installed",
        service="agent",
        session_id=get_session_id(),
        loop_id=id(loop)
    )

