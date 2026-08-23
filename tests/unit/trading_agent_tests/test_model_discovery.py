"""Unit tests for transformer model discovery."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("MODEL_DIR", "./test_models")
os.environ.setdefault("MODEL_PATH", "")

from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.transformer_node import TransformerModelNode
from feature_store.transformer_btcusd.contract import (
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    bundle_dir_name,
    model_family_for_resolution,
    onnx_filename_for_resolution,
)


@pytest.fixture
def temp_model_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def model_registry() -> MCPModelRegistry:
    return MCPModelRegistry()


def _write_transformer_bundle(model_dir: Path, name: str = "test_transformer") -> Path:
    src = Path("agent/model_storage/JackSparrow_Transformer_BTCUSD_15m")
    meta = model_dir / TRANSFORMER_METADATA_FILENAME
    meta.write_text(
        json.dumps(
            {
                "model_name": name,
                "version": "transformer_v1",
                "model_family": model_family_for_resolution("15m"),
                "resolution": "15m",
                "onnx_filename": onnx_filename_for_resolution("15m"),
                "default_threshold": 0.005,
            }
        ),
        encoding="utf-8",
    )
    onnx_name = onnx_filename_for_resolution("15m")
    shutil.copy2(src / onnx_name, model_dir / onnx_name)
    shutil.copy2(src / TRANSFORMER_FEATURE_CONFIG_FILENAME, model_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME)
    return meta


@pytest.mark.asyncio
async def test_discover_prefers_fusion_bundle_over_per_tf(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    from agent.models.fusion_node import FusionModelNode
    from feature_store.transformer_btcusd.contract import FUSION_BUNDLE_DIR_NAME

    fusion_dir = temp_model_dir / FUSION_BUNDLE_DIR_NAME
    fusion_dir.mkdir(parents=True)
    (fusion_dir / TRANSFORMER_METADATA_FILENAME).write_text(
        json.dumps(
            {
                "model_name": "fusion_model",
                "model_family": "jacksparrow_transformer_btcusd_mtf_fusion",
                "resolution": "mtf_fusion",
                "onnx_filename": "btcusd_mtf_fusion.onnx",
            }
        ),
        encoding="utf-8",
    )
    (fusion_dir / "btcusd_mtf_fusion.onnx").write_bytes(b"onnx")
    (fusion_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME).write_text("{}", encoding="utf-8")
    tf_dir = temp_model_dir / bundle_dir_name("15m")
    tf_dir.mkdir(parents=True)
    _write_transformer_bundle(tf_dir)

    mock_fusion = MagicMock(spec=FusionModelNode)
    mock_fusion.model_name = "fusion_model"
    mock_fusion.model_type = "transformer_mtf_fusion"
    mock_fusion.resolution = "mtf_fusion"
    mock_fusion.initialize = AsyncMock()

    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = True
        mock_settings.transformer_decision_path = "mtf_fusion"
        with patch.object(FusionModelNode, "from_metadata_path", return_value=mock_fusion):
            discovery = ModelDiscovery(model_registry)
            discovered = await discovery.discover_models()

    assert discovered == ["fusion_model"]
    assert model_registry.get_model("fusion_model") is mock_fusion


@pytest.mark.asyncio
async def test_discover_transformer_registers_when_auto_register(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    bundle_dir = temp_model_dir / bundle_dir_name("15m")
    bundle_dir.mkdir(parents=True)
    _write_transformer_bundle(bundle_dir)
    mock_node = MagicMock(spec=TransformerModelNode)
    mock_node.model_name = "test_transformer"
    mock_node.model_type = "transformer"
    mock_node.initialize = AsyncMock()

    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = True

        with patch.object(
            TransformerModelNode, "from_metadata_path", return_value=mock_node
        ):
            discovery = ModelDiscovery(model_registry)
            discovered = await discovery.discover_models()

    assert discovered == ["test_transformer"]
    mock_node.initialize.assert_awaited_once()
    assert model_registry.get_model("test_transformer") is mock_node


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
async def test_discover_fails_without_onnx(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / bundle_dir_name("15m")
    bundle.mkdir(parents=True)
    (bundle / TRANSFORMER_METADATA_FILENAME).write_text("{}", encoding="utf-8")

    from agent.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "model_dir", str(tmp_path))
    monkeypatch.setattr(config_mod.settings, "model_auto_register", True)

    registry = MCPModelRegistry()
    await registry.initialize()
    discovery = ModelDiscovery(registry)
    discovered = await discovery.discover_models()
    assert discovered == []
    assert len(registry.models) == 0
