"""Tracked fire-and-forget asyncio tasks with error logging and shutdown cancellation."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, Optional, Set

import structlog

logger = structlog.get_logger()

_background_tasks: Set[asyncio.Task] = set()


def fire_and_forget(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str = "bg_task",
) -> asyncio.Task:
    """Schedule a coroutine; log failures; track for graceful shutdown."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_log_task_failure)
    return task


def _log_task_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "background_task_failed",
            task_name=task.get_name(),
            error=str(exc),
            exc_info=exc,
        )


async def cancel_background_tasks(timeout: float = 5.0) -> None:
    """Cancel all tracked background tasks (e.g. on agent shutdown)."""
    pending = [t for t in list(_background_tasks) if not t.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    _background_tasks.difference_update(pending)


def background_task_count() -> int:
    return len(_background_tasks)
