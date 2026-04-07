"""
Model discovery service.

Automatically discovers and registers ML models from storage directory.
"""

import json
from typing import List
from pathlib import Path
import structlog

from agent.core.config import settings
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.mcp_model_node import MCPModelNode

logger = structlog.get_logger()


class ModelDiscovery:
    """Model discovery service."""
    
    def __init__(self, registry: MCPModelRegistry):
        """Initialize model discovery."""
        self.registry = registry
        self.model_dir = Path(settings.model_dir)
        self.model_path = settings.model_path
        self.auto_register = settings.model_auto_register
    
    async def discover_models(self) -> List[str]:
        """Discover and register models.
        
        Returns:
            List of successfully discovered model names
            
        Note:
            This method will continue discovery even if individual models fail.
            Errors are logged but do not crash the agent.
            Duplicate models (same name) are skipped - MODEL_PATH takes precedence over MODEL_DIR.
        """
        
        discovered_models = []
        failed_models = []
        failed_reasons: List[str] = []
        discovery_attempted = False
        loaded_model_names = set()  # Track loaded model names to prevent duplicates
        
        logger.info(
            "model_discovery_starting",
            model_path=self.model_path,
            model_dir=str(self.model_dir),
            discovery_enabled=settings.model_discovery_enabled,
            auto_register=settings.model_auto_register,
            discovery_mode="multi_format",
            model_format=getattr(settings, "model_format", "auto"),
            message="Starting model discovery process",
        )
        
        try:
            single_model_mode = bool(
                getattr(settings, "single_model_mode_enabled", False)
            )
            if single_model_mode:
                from agent.models.consolidated_model_node import ConsolidatedModelNode

                pattern = str(
                    getattr(
                        settings,
                        "consolidated_model_metadata_glob",
                        "metadata_BTCUSD_consolidated*.json",
                    )
                    or "metadata_BTCUSD_consolidated*.json"
                )
                strict_single = bool(
                    getattr(settings, "single_model_strict_startup", False)
                )
                recursive = getattr(settings, "model_discovery_recursive", True)
                if recursive:
                    metadata_files = sorted(self.model_dir.rglob(pattern))
                else:
                    metadata_files = sorted(self.model_dir.glob(pattern))

                discovery_attempted = True
                logger.info(
                    "model_discovery_single_model_scan",
                    model_dir=str(self.model_dir),
                    metadata_pattern=pattern,
                    recursive=recursive,
                    files_found=len(metadata_files),
                )
                if not metadata_files:
                    msg = (
                        "No consolidated metadata file found for single-model mode "
                        f"(pattern={pattern})."
                    )
                    if strict_single:
                        raise RuntimeError(msg)
                    logger.warning(
                        "model_discovery_single_model_not_found",
                        message=msg,
                    )
                else:
                    # Prefer the newest file when multiple artifacts are present.
                    metadata_path = max(
                        metadata_files, key=lambda p: p.stat().st_mtime
                    )
                    node = ConsolidatedModelNode.from_metadata(metadata_path)
                    await node.initialize()
                    self._handle_discovered_model(node, discovered_models)
                    loaded_model_names.add(node.model_name)
                    logger.info(
                        "model_discovered_single_model",
                        model_name=node.model_name,
                        model_path=str(metadata_path),
                        model_type=node.model_type,
                    )
                self.registry.record_discovery_summary(
                    discovered_models,
                    failed_models,
                    failed_reasons,
                    discovery_attempted=discovery_attempted,
                )
                return discovered_models

            # V4-only discovery: load BTCUSD ensembles from metadata_BTCUSD_*.json
            # under MODEL_DIR (typically agent/model_storage/jacksparrow_v4_BTCUSD).
            if not settings.model_discovery_enabled:
                logger.info(
                    "model_discovery_disabled_v4_only",
                    model_dir=str(self.model_dir),
                    discovery_mode="v4_only",
                    message="Model discovery is disabled via settings; skipping v4 discovery",
                )
            else:
                model_dir_abs = self.model_dir.resolve()
                if not self.model_dir.exists():
                    discovery_attempted = True
                    logger.warning(
                        "model_dir_not_found_v4_only",
                        model_dir=str(self.model_dir),
                        absolute_path=str(model_dir_abs),
                        discovery_mode="v4_only",
                        message=(
                            "MODEL_DIR does not exist, skipping v4 metadata discovery. "
                            "Set MODEL_DIR to the v4 folder (for example "
                            "./agent/model_storage/jacksparrow_v4_BTCUSD)."
                        ),
                    )
                else:
                    recursive = getattr(
                        settings, "model_discovery_recursive", True
                    )
                    if recursive:
                        v4_metadata_files = sorted(
                            self.model_dir.rglob("metadata_BTCUSD_*.json")
                        )
                    else:
                        v4_metadata_files = sorted(
                            self.model_dir.glob("metadata_BTCUSD_*.json")
                        )
                    discovery_attempted = True
                    logger.info(
                        "model_discovery_v4_scan",
                        model_dir=str(self.model_dir),
                        absolute_path=str(model_dir_abs),
                        discovery_mode="v4_only",
                        recursive=recursive,
                        files_found=len(v4_metadata_files),
                        file_list=[str(p) for p in v4_metadata_files[:10]],
                    )

                    if not v4_metadata_files:
                        logger.info(
                            "model_discovery_v4_no_metadata_files",
                            model_dir=str(self.model_dir),
                            absolute_path=str(model_dir_abs),
                            discovery_mode="v4_only",
                            recursive=recursive,
                            message=(
                                "No metadata_BTCUSD_*.json files found under MODEL_DIR for v4 discovery. "
                                "Set MODEL_DIR to the bundle folder, or enable "
                                "MODEL_DISCOVERY_RECURSIVE=true to scan subfolders "
                                "(for example ./agent/model_storage)."
                            ),
                        )
                    else:
                        from agent.models.v4_ensemble_node import V4EnsembleNode
                        from agent.models.pipeline_v15_node import (
                            PipelineV15Node,
                            metadata_is_v15_pipeline,
                        )

                        model_fmt = (
                            getattr(settings, "model_format", "auto") or "auto"
                        ).strip().lower()

                        for meta_path in v4_metadata_files:
                            try:
                                with meta_path.open("r", encoding="utf-8") as mf:
                                    raw_meta = json.load(mf)
                                is_v15 = metadata_is_v15_pipeline(meta_path, raw_meta)

                                if model_fmt == "v4_ensemble" and is_v15:
                                    continue
                                if model_fmt == "v15_pipeline" and not is_v15:
                                    continue

                                if is_v15:
                                    node = PipelineV15Node.from_metadata_path(meta_path)
                                    await node.initialize()
                                    disc_mode = "v15_pipeline"
                                else:
                                    node = V4EnsembleNode.from_metadata(meta_path)
                                    await node.initialize()
                                    disc_mode = "v4_ensemble"

                                if node.model_name in loaded_model_names:
                                    logger.warning(
                                        "model_discovery_duplicate_skipped",
                                        model_name=node.model_name,
                                        model_path=str(meta_path),
                                        reason="duplicate model_name",
                                        discovery_mode=disc_mode,
                                    )
                                    continue
                                self._handle_discovered_model(node, discovered_models)
                                loaded_model_names.add(node.model_name)
                                logger.info(
                                    "model_discovered",
                                    model_name=node.model_name,
                                    model_path=str(meta_path),
                                    model_type=node.model_type,
                                    discovery_mode=disc_mode,
                                )
                            except Exception as e:
                                failed_models.append(str(meta_path))
                                error_type = type(e).__name__
                                failed_reasons.append(f"{meta_path}: {error_type} - {str(e)}")
                                logger.error(
                                    "model_discovery_metadata_failed",
                                    model_file=str(meta_path),
                                    error=str(e),
                                    error_type=error_type,
                                    exc_info=True,
                                    message="Failed to load model metadata; continuing with other files",
                                )
        except Exception as e:
            logger.critical(
                "model_discovery_critical_error",
                error=str(e),
                discovery_mode="multi_format",
                exc_info=True,
                message="Critical error in model discovery, but agent will continue"
            )
        
        # Log summary with accurate counts
        successful_count = len(discovered_models)
        failed_count = len(failed_models)
        total_attempted = successful_count + failed_count
        
        if discovered_models:
            message = (
                f"Model discovery complete: {successful_count} model(s) loaded successfully"
            )
            if failed_count > 0:
                message += f", {failed_count} model(s) failed to load"
            
            logger.info(
                "model_discovery_complete",
                discovered_count=successful_count,
                failed_count=failed_count,
                total_attempted=total_attempted,
                discovery_mode="multi_format",
                discovery_attempted=discovery_attempted,
                models=discovered_models,
                failed_files=failed_models[:5] if failed_models else [],  # Log first 5 failed files
                message=message
            )
        else:
            # Provide clearer message based on whether discovery was attempted
            if discovery_attempted:
                if failed_count > 0:
                    message = f"Model discovery attempted but no models loaded successfully ({failed_count} failed, {total_attempted} total attempted). Agent will continue in monitoring mode without ML predictions."
                elif total_attempted == 0:
                    message = f"Model discovery attempted but no model files found in MODEL_DIR. Agent will continue in monitoring mode without ML predictions."
                else:
                    message = f"No models were successfully discovered ({failed_count} failed, {total_attempted} total attempted). Agent will continue in monitoring mode without ML predictions."
            else:
                message = "Model discovery was not attempted. Check MODEL_DISCOVERY_ENABLED setting. Agent will continue in monitoring mode without ML predictions."
            
            logger.warning(
                "model_discovery_no_models",
                failed_count=failed_count,
                total_attempted=total_attempted,
                discovery_attempted=discovery_attempted,
                discovery_mode="v4_only",
                discovery_enabled=settings.model_discovery_enabled,
                failed_files=failed_models[:5] if failed_models else [],  # Log first 5 failed files
                model_path=self.model_path,
                model_dir=str(self.model_dir),
                model_dir_exists=self.model_dir.exists(),
                message=message
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
        model_node: MCPModelNode,
        discovered_models: List[str]
    ) -> None:
        """Register or queue discovered models based on configuration."""
        discovered_models.append(model_node.model_name)
        if self.auto_register:
            self.registry.register_model(model_node)
        else:
            self.registry.add_pending_model(model_node)
            logger.info(
                "model_discovery_pending_model",
                model_name=model_node.model_name,
                model_type=model_node.model_type,
                reason="model_auto_register disabled"
            )
    
