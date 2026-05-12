"""Unit tests for JackSparrow v43-only model discovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("MODEL_DIR", "./test_models")
os.environ.setdefault("MODEL_PATH", "")

from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry


@pytest.fixture
def temp_model_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def model_registry() -> MCPModelRegistry:
    return MCPModelRegistry()


def _write_meta(model_dir: Path, name: str = "test_v43") -> Path:
    meta = model_dir / "metadata_v43.json"
    meta.write_text(
        json.dumps(
            {
                "model_name": name,
                "version": "v43",
                "features": ["ret_1"],
            }
        ),
        encoding="utf-8",
    )
    return meta


def _write_meta_v44(model_dir: Path, name: str = "test_v44") -> Path:
    meta = model_dir / "metadata_v44.json"
    meta.write_text(
        json.dumps(
            {
                "model_name": name,
                "version": "v44",
                "features": ["ret_1"],
            }
        ),
        encoding="utf-8",
    )
    return meta


@pytest.mark.asyncio
async def test_discover_v43_registers_when_auto_register(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    _write_meta(temp_model_dir)
    mock_node = MagicMock(spec=JackSparrowV43Node)
    mock_node.model_name = "test_v43"
    mock_node.model_type = "jacksparrow_v43"
    mock_node.initialize = AsyncMock()

    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = True

        with patch.object(JackSparrowV43Node, "from_metadata_path", return_value=mock_node):
            discovery = ModelDiscovery(model_registry)
            discovered = await discovery.discover_models()

    assert discovered == ["test_v43"]
    mock_node.initialize.assert_awaited_once()
    assert model_registry.get_model("test_v43") is mock_node


@pytest.mark.asyncio
async def test_discover_v43_pending_when_auto_register_off(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    _write_meta(temp_model_dir)
    mock_node = MagicMock(spec=JackSparrowV43Node)
    mock_node.model_name = "test_v43"
    mock_node.model_type = "jacksparrow_v43"
    mock_node.initialize = AsyncMock()

    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = False

        with patch.object(JackSparrowV43Node, "from_metadata_path", return_value=mock_node):
            discovery = ModelDiscovery(model_registry)
            discovered = await discovery.discover_models()

    assert discovered == ["test_v43"]
    assert model_registry.get_model("test_v43") is None
    assert "test_v43" in model_registry.list_pending_models()


@pytest.mark.asyncio
async def test_discover_empty_when_metadata_missing(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = True

        discovery = ModelDiscovery(model_registry)
        discovered = await discovery.discover_models()

    assert discovered == []
    assert model_registry.list_models() == []


@pytest.mark.asyncio
async def test_discover_empty_when_model_dir_missing(model_registry: MCPModelRegistry) -> None:
    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = "/nonexistent/jacksparrow_bundle"
        mock_settings.model_path = None
        mock_settings.model_auto_register = True

        discovery = ModelDiscovery(model_registry)
        discovered = await discovery.discover_models()

    assert discovered == []
    assert model_registry.list_models() == []


@pytest.mark.asyncio
async def test_discover_v44_metadata_is_accepted(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    meta_path = _write_meta_v44(temp_model_dir)
    mock_node = MagicMock(spec=JackSparrowV43Node)
    mock_node.model_name = "test_v44"
    mock_node.model_type = "jacksparrow_v43"
    mock_node.initialize = AsyncMock()

    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = True

        with patch.object(JackSparrowV43Node, "from_metadata_path", return_value=mock_node) as factory:
            discovery = ModelDiscovery(model_registry)
            discovered = await discovery.discover_models()

    assert discovered == ["test_v44"]
    factory.assert_called_once_with(meta_path)
