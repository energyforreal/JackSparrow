"""Unit tests for IC model discovery."""

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

from agent.intelligence.ic_node import IC_MODEL_FAMILY, RuleBasedIntelligenceNode
from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES, V43_COMPATIBLE_FEATURE_VERSION
from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEY_TO_BARS, V43_HORIZON_KEYS


@pytest.fixture
def temp_model_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def model_registry() -> MCPModelRegistry:
    return MCPModelRegistry()


def _write_ic_meta(model_dir: Path, name: str = "test_ic") -> Path:
    thr = 0.005
    horizons = {
        key: {
            "forward_bars": V43_HORIZON_KEY_TO_BARS[key],
            "horizon_minutes": V43_HORIZON_KEY_TO_BARS[key] * 5,
            "horizon_key": key,
            "validation_metrics": {"dynamic_threshold": thr, "short_threshold": thr},
        }
        for key in V43_HORIZON_KEYS
    }
    meta = model_dir / "metadata_ic.json"
    meta.write_text(
        json.dumps(
            {
                "model_name": name,
                "version": "ic_v1",
                "model_family": IC_MODEL_FAMILY,
                "compatible_feature_version": V43_COMPATIBLE_FEATURE_VERSION,
                "features": list(V43_CANONICAL_FEATURES),
                "primary_execution_horizon_bars": 2,
                "horizons": horizons,
            }
        ),
        encoding="utf-8",
    )
    return meta


@pytest.mark.asyncio
async def test_discover_ic_registers_when_auto_register(
    temp_model_dir: Path, model_registry: MCPModelRegistry
) -> None:
    _write_ic_meta(temp_model_dir)
    mock_node = MagicMock(spec=RuleBasedIntelligenceNode)
    mock_node.model_name = "test_ic"
    mock_node.model_type = "rule_based_intelligence"
    mock_node.initialize = AsyncMock()

    with patch("agent.models.model_discovery.settings") as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_auto_register = True

        with patch.object(
            RuleBasedIntelligenceNode, "from_metadata_path", return_value=mock_node
        ):
            discovery = ModelDiscovery(model_registry)
            discovered = await discovery.discover_models()

    assert discovered == ["test_ic"]
    mock_node.initialize.assert_awaited_once()
    assert model_registry.get_model("test_ic") is mock_node


@pytest.mark.asyncio
async def test_discover_empty_when_metadata_ic_missing(
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
