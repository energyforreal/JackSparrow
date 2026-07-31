"""
Model discovery: transformer ONNX bundle only.
"""

import structlog
from pathlib import Path
from typing import List

from agent.core.config import settings
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.transformer_node import TransformerModelNode
from feature_store.transformer_btcusd_15m.contract import (
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    TRANSFORMER_ONNX_FILENAME,
)

logger = structlog.get_logger()


def _resolve_transformer_metadata_path(model_dir: Path) -> Path | None:
    candidate = model_dir / TRANSFORMER_METADATA_FILENAME
    if candidate.is_file():
        return candidate
    return None


class ModelDiscovery:
    """Discovers transformer bundle from MODEL_DIR."""

    def __init__(self, registry: MCPModelRegistry):
        self.registry = registry
        self.model_dir = Path(settings.model_dir)
        self.model_path = settings.model_path
        self.auto_register = settings.model_auto_register

    async def discover_models(self) -> List[str]:
        discovered_models: List[str] = []
        failed_models: List[str] = []
        failed_reasons: List[str] = []
        discovery_attempted = True

        logger.info(
            "model_discovery_start",
            model_dir=str(self.model_dir),
            model_path=self.model_path,
            auto_register=self.auto_register,
        )

        if self.model_path:
            logger.warning(
                "model_discovery_model_path_ignored",
                model_path=self.model_path,
                message="MODEL_PATH is ignored; use MODEL_DIR pointing at a model bundle.",
            )

        if not self.model_dir.is_dir():
            msg = f"MODEL_DIR is not a directory: {self.model_dir}"
            logger.error("model_discovery_bundle_missing", message=msg)
            failed_models.append(str(self.model_dir))
            failed_reasons.append(msg)
            self.registry.record_discovery_summary(
                discovered_models,
                failed_models,
                failed_reasons,
                discovery_attempted=discovery_attempted,
            )
            return discovered_models

        transformer_meta = _resolve_transformer_metadata_path(self.model_dir)
        if not transformer_meta:
            msg = (
                f"No {TRANSFORMER_METADATA_FILENAME} found in {self.model_dir}. "
                "Train in Colab and copy ONNX exports into the bundle."
            )
            logger.error("model_discovery_transformer_missing", message=msg)
            failed_models.append(str(self.model_dir))
            failed_reasons.append(msg)
            self.registry.record_discovery_summary(
                discovered_models,
                failed_models,
                failed_reasons,
                discovery_attempted=discovery_attempted,
            )
            return discovered_models

        onnx_path = self.model_dir / TRANSFORMER_ONNX_FILENAME
        cfg_path = self.model_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
        for artifact_path, label in (
            (onnx_path, TRANSFORMER_ONNX_FILENAME),
            (cfg_path, TRANSFORMER_FEATURE_CONFIG_FILENAME),
        ):
            if not artifact_path.is_file():
                msg = f"Missing {label} in {self.model_dir}"
                logger.error("model_discovery_artifact_missing", artifact=label, message=msg)
                failed_models.append(str(artifact_path))
                failed_reasons.append(msg)
                self.registry.record_discovery_summary(
                    discovered_models,
                    failed_models,
                    failed_reasons,
                    discovery_attempted=discovery_attempted,
                )
                return discovered_models

        try:
            node = TransformerModelNode.from_metadata_path(transformer_meta)
            await node.initialize()
            if self.auto_register:
                self.registry.register_model(node)
                discovered_models.append(node.model_name)
                logger.info(
                    "model_discovered_transformer",
                    model_name=node.model_name,
                    metadata=str(transformer_meta),
                )
            else:
                self.registry.add_pending_model(node)
                discovered_models.append(f"pending:{node.model_name}")
        except Exception as exc:
            msg = f"Transformer bundle load failed: {exc}"
            logger.error(
                "model_discovery_transformer_failed",
                metadata=str(transformer_meta),
                error=str(exc),
                exc_info=True,
            )
            failed_models.append(str(transformer_meta))
            failed_reasons.append(msg)

        self.registry.record_discovery_summary(
            discovered_models,
            failed_models,
            failed_reasons,
            discovery_attempted=discovery_attempted,
        )
        return discovered_models
