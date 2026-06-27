"""Backward-compatible re-export shim for entry validation guard."""

from agent.core.config import settings
from agent.core.entry_validation_guard import (  # noqa: F401
    validate_entry_signal,
    validate_ml_entry_signal,
)

__all__ = ["validate_entry_signal", "validate_ml_entry_signal", "settings"]
