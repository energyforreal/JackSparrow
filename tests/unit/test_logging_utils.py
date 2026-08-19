"""Tests for agent exception logging helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.core.exception_handlers import _async_exception_handler


def test_async_exception_handler_does_not_raise_on_context_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handler used to TypeError by passing component= and **log_context."""
    mock_logger = MagicMock()
    monkeypatch.setattr("agent.core.logging_utils.structlog.get_logger", lambda: mock_logger)
    monkeypatch.setattr("agent.core.exception_handlers.logger", mock_logger)

    loop = MagicMock()
    _async_exception_handler(
        loop,
        {
            "exception": ModuleNotFoundError(
                "No module named 'agent.learning.threshold_adapter'"
            ),
            "message": "Task exception was never retrieved",
            "future": None,
        },
    )

    mock_logger.error.assert_called()
