"""
JackSparrow model discovery (v43 primary + optional MSO v50).

Loads v43 bundle from ``settings.model_dir`` and optionally
``metadata_mso_v50.json`` + ``model_artifact_mso_v50.pkl`` when present.
"""

import structlog
from pathlib import Path
from typing import List, Optional

from agent.core.config import settings
from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
from agent.models.market_state_node import MarketStateOracleNode
from agent.models.mcp_model_registry import MCPModelRegistry

logger = structlog.get_logger()

_SUPPORTED_METADATA_FILENAMES = ("metadata_v43.json", "metadata_v44.json")
_MSO_METADATA_FILENAME = "metadata_mso_v50.json"


def _resolve_bundle_metadata_path(model_dir: Path) -> Optional[Path]:
    """Resolve known bundle metadata names in priority order."""
    for filename in _SUPPORTED_METADATA_FILENAMES:
        candidate = model_dir / filename
        if candidate.is_file():
            return candidate
    return None


class ModelDiscovery:
    """Discovers v43 bundle and optional MSO market-state oracle."""

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
            mso_enabled=bool(getattr(settings, "mso_model_enabled", False)),
        )

        try:
            names = (
                sorted(p.name for p in self.model_dir.iterdir())
                if self.model_dir.is_dir()
                else []
            )
        except Exception as ex:
            names = [f"<listdir_error:{ex}>"]

        if self.model_path:
            logger.warning(
                "model_discovery_model_path_ignored",
                model_path=self.model_path,
                message="MODEL_PATH is ignored; use MODEL_DIR pointing to the v43 bundle.",
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

        meta_path = _resolve_bundle_metadata_path(self.model_dir)
        if not meta_path:
            msg = (
                f"No supported metadata file under {self.model_dir}; "
                f"expected one of {', '.join(_SUPPORTED_METADATA_FILENAMES)}"
            )
            logger.error("model_discovery_v43_metadata_missing", message=msg)
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
            node = JackSparrowV43Node.from_metadata_path(meta_path)
            await node.initialize()
            self._handle_discovered_model(node, discovered_models)
            logger.info(
                "model_discovered_v43",
                model_name=node.model_name,
                model_path=str(meta_path),
                model_type=node.model_type,
            )
        except Exception as exc:
            failed_models.append(str(meta_path))
            failed_reasons.append(f"{meta_path.name}: {type(exc).__name__}: {exc}")
            logger.error(
                "model_discovery_v43_failed",
                model_path=str(meta_path),
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
                message="v43 model load failed",
            )

        mso_meta = self.model_dir / _MSO_METADATA_FILENAME
        if mso_meta.is_file() and bool(getattr(settings, "mso_model_enabled", False)):
            try:
                mso_node = MarketStateOracleNode.from_metadata_path(mso_meta)
                await mso_node.initialize()
                self._handle_discovered_model_mso(mso_node, discovered_models)
                logger.info(
                    "model_discovered_mso",
                    model_name=mso_node.model_name,
                    model_path=str(mso_meta),
                )
            except Exception as exc:
                failed_models.append(str(mso_meta))
                failed_reasons.append(f"{mso_meta.name}: {type(exc).__name__}: {exc}")
                logger.error(
                    "model_discovery_mso_failed",
                    model_path=str(mso_meta),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
        elif mso_meta.is_file():
            logger.info(
                "model_discovery_mso_skipped",
                reason="MSO_MODEL_ENABLED=false",
                metadata=str(mso_meta),
            )

        self.registry.record_discovery_summary(
            discovered_models,
            failed_models,
            failed_reasons,
            discovery_attempted=discovery_attempted,
        )
        return discovered_models

    def _handle_discovered_model(
        self,
        model_node: JackSparrowV43Node,
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

    def _handle_discovered_model_mso(
        self,
        model_node: MarketStateOracleNode,
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
