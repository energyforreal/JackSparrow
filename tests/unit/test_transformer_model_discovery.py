"""Transformer-only model discovery tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from feature_store.transformer_btcusd_15m.contract import (
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    TRANSFORMER_ONNX_FILENAME,
)


@pytest.mark.asyncio
async def test_discover_transformer_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    src = Path("agent/model_storage/JackSparrow_Transformer_BTCUSD")
    (bundle / TRANSFORMER_METADATA_FILENAME).write_text(
        (src / "metadata_transformer.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in (TRANSFORMER_ONNX_FILENAME, TRANSFORMER_FEATURE_CONFIG_FILENAME):
        shutil.copy2(src / name, bundle / name)

    from agent.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "model_dir", str(bundle))
    monkeypatch.setattr(config_mod.settings, "model_auto_register", True)

    registry = MCPModelRegistry()
    await registry.initialize()
    discovery = ModelDiscovery(registry)
    discovered = await discovery.discover_models()
    assert discovered
    assert len(registry.models) == 1


@pytest.mark.asyncio
async def test_discover_fails_without_onnx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / TRANSFORMER_METADATA_FILENAME).write_text("{}", encoding="utf-8")

    from agent.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "model_dir", str(bundle))

    registry = MCPModelRegistry()
    await registry.initialize()
    discovery = ModelDiscovery(registry)
    discovered = await discovery.discover_models()
    assert discovered == []
    assert len(registry.models) == 0
