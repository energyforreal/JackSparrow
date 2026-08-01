"""
Model discovery: per-TF transformer ONNX bundles.
"""

import structlog
from pathlib import Path
from typing import List

from agent.core.config import settings
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.transformer_node import TransformerModelNode
from feature_store.transformer_btcusd.contract import (
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    bundle_dir_name,
)

logger = structlog.get_logger()

_BUNDLE_PREFIX = "JackSparrow_Transformer_BTCUSD"


def _resolve_bundle_dirs(model_dir: Path) -> List[Path]:
    """Return bundle directories containing metadata_transformer.json."""
    bundles: List[Path] = []
    if (model_dir / TRANSFORMER_METADATA_FILENAME).is_file():
        bundles.append(model_dir)
    if model_dir.is_dir():
        for child in sorted(model_dir.iterdir()):
            if not child.is_dir():
                continue
            if not child.name.startswith(_BUNDLE_PREFIX):
                continue
            if (child / TRANSFORMER_METADATA_FILENAME).is_file():
                bundles.append(child)
    return bundles


def _validate_bundle_artifacts(bundle_dir: Path, metadata: dict) -> str | None:
    """Return error message if bundle artifacts are missing."""
    resolution = str(metadata.get("resolution") or "15m")
    onnx_name = str(metadata.get("onnx_filename") or f"btcusd_{resolution}_transformer.onnx")
    onnx_path = bundle_dir / onnx_name
    cfg_path = bundle_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    for artifact_path, label in ((onnx_path, onnx_name), (cfg_path, TRANSFORMER_FEATURE_CONFIG_FILENAME)):
        if not artifact_path.is_file():
            return f"Missing {label} in {bundle_dir}"
    return None


class ModelDiscovery:
    """Discovers per-TF transformer bundles under MODEL_DIR."""

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
                message="MODEL_PATH is ignored; use MODEL_DIR pointing at model storage.",
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

        bundle_dirs = _resolve_bundle_dirs(self.model_dir)
        if not bundle_dirs:
            msg = (
                f"No {TRANSFORMER_METADATA_FILENAME} found under {self.model_dir}. "
                f"Expected subdirs like {bundle_dir_name('15m')}/."
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

        for bundle_dir in bundle_dirs:
            meta_path = bundle_dir / TRANSFORMER_METADATA_FILENAME
            try:
                import json

                raw = json.loads(meta_path.read_text(encoding="utf-8"))
                artifact_err = _validate_bundle_artifacts(bundle_dir, raw)
                if artifact_err:
                    failed_models.append(str(bundle_dir))
                    failed_reasons.append(artifact_err)
                    continue

                node = TransformerModelNode.from_metadata_path(meta_path)
                await node.initialize()
                if self.auto_register:
                    self.registry.register_model(node)
                    discovered_models.append(node.model_name)
                    logger.info(
                        "model_discovered_transformer",
                        model_name=node.model_name,
                        resolution=node.resolution,
                        metadata=str(meta_path),
                    )
                else:
                    self.registry.add_pending_model(node)
                    discovered_models.append(f"pending:{node.model_name}")
            except Exception as exc:
                msg = f"Failed to load transformer bundle {bundle_dir}: {exc}"
                logger.error("model_discovery_transformer_failed", error=msg, exc_info=True)
                failed_models.append(str(bundle_dir))
                failed_reasons.append(msg)

        self.registry.record_discovery_summary(
            discovered_models,
            failed_models,
            failed_reasons,
            discovery_attempted=discovery_attempted,
        )
        return discovered_models
