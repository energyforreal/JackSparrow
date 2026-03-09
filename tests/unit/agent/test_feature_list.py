"""Tests for canonical feature list (training/runtime alignment)."""

import sys
from pathlib import Path

# Ensure project root is on path (for agent imports)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from agent.data.feature_list import (
    FEATURE_LIST,
    EXPECTED_FEATURE_COUNT,
    get_feature_list,
    validate_feature_count,
)


def test_feature_list_has_expected_count():
    """Canonical list must have 50 features."""
    assert len(FEATURE_LIST) == 50
    assert EXPECTED_FEATURE_COUNT == 50


def test_get_feature_list_returns_copy():
    """get_feature_list returns a copy so callers cannot mutate the canonical list."""
    lst = get_feature_list()
    assert lst == FEATURE_LIST
    assert lst is not FEATURE_LIST


def test_validate_feature_count():
    """validate_feature_count returns True only for expected count."""
    assert validate_feature_count(FEATURE_LIST) is True
    assert validate_feature_count(get_feature_list()) is True
    assert validate_feature_count(FEATURE_LIST[:49]) is False
    assert validate_feature_count(FEATURE_LIST + ["extra"]) is False


def test_mcp_orchestrator_required_features_match_canonical():
    """MCP orchestrator _get_required_features() must match canonical list."""
    from agent.core.mcp_orchestrator import MCPOrchestrator
    orch = MCPOrchestrator()
    required = orch._get_required_features()
    assert len(required) == EXPECTED_FEATURE_COUNT
    assert required == get_feature_list()  # same contents (get_feature_list returns copy)
