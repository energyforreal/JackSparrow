"""
Model discovery: rule-based Intelligence Component (IC) bundle only.
"""

import structlog
from pathlib import Path
from typing import List, Optional

from agent.core.config import settings
from agent.intelligence.ic_node import IC_METADATA_FILENAME, RuleBasedIntelligenceNode
from agent.models.mcp_model_registry import MCPModelRegistry

logger = structlog.get_logger()


def _resolve_ic_metadata_path(model_dir: Path) -> Optional[Path]:
    candidate = model_dir / IC_METADATA_FILENAME
    if candidate.is_file():
        return candidate
    return None


class ModelDiscovery:
    """Discovers the rule-based IC bundle from MODEL_DIR."""

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
            ic_mode=True,
        )

        if self.model_path:
            logger.warning(
                "model_discovery_model_path_ignored",
                model_path=self.model_path,
                message="MODEL_PATH is ignored; use MODEL_DIR pointing at the IC bundle.",
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

        ic_meta = _resolve_ic_metadata_path(self.model_dir)
        if not ic_meta:
            msg = (
                f"No {IC_METADATA_FILENAME} under {self.model_dir}; "
                "point MODEL_DIR at agent/model_storage/JackSparrow_IC_BTCUSD"
            )
            logger.error("model_discovery_ic_metadata_missing", message=msg)
            failed_models.append(str(self.model_dir))
            failed_reasons.append(msg)
            self.registry.record_discovery_summary(
                discovered_models,
                failed_models,
                failed_reasons,
                discovery_attempted=discovery_attempted,
            )
            return discovered_models

        try:
            node = RuleBasedIntelligenceNode.from_metadata_path(ic_meta)
            await node.initialize()
            self._register_node(node, discovered_models)
            logger.info(
                "model_discovered_ic",
                model_name=node.model_name,
                model_path=str(ic_meta),
                model_type=node.model_type,
            )
        except Exception as exc:
            failed_models.append(str(ic_meta))
            failed_reasons.append(f"{ic_meta.name}: {type(exc).__name__}: {exc}")
            logger.error(
                "model_discovery_ic_failed",
                model_path=str(ic_meta),
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

        self.registry.record_discovery_summary(
            discovered_models,
            failed_models,
            failed_reasons,
            discovery_attempted=discovery_attempted,
        )
        return discovered_models

    def _register_node(
        self,
        model_node: RuleBasedIntelligenceNode,
        discovered_models: List[str],
    ) -> None:
        discovered_models.append(model_node.model_name)
        if self.auto_register:
            self.registry.register_model(model_node)
        else:
            self.registry.add_pending_model(model_node)
            logger.info(
                "model_discovery_pending_model",
                model_name=model_node.model_name,
                model_type=model_node.model_type,
                reason="model_auto_register disabled",
            )
