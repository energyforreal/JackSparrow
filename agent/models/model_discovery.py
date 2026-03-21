"""
Model discovery service.

Automatically discovers and registers ML models from storage directory.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import pickle
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
            discovery_mode="v4_only",
            message="Starting model discovery process (v4-only mode)"
        )
        
        try:
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

                        for meta_path in v4_metadata_files:
                            try:
                                node = V4EnsembleNode.from_metadata(meta_path)
                                await node.initialize()
                                if node.model_name in loaded_model_names:
                                    logger.warning(
                                        "model_discovery_duplicate_skipped",
                                        model_name=node.model_name,
                                        model_path=str(meta_path),
                                        reason="v4 ensemble with same name already loaded",
                                        discovery_mode="v4_only",
                                    )
                                    continue
                                self._handle_discovered_model(node, discovered_models)
                                loaded_model_names.add(node.model_name)
                                logger.info(
                                    "model_discovered",
                                    model_name=node.model_name,
                                    model_path=str(meta_path),
                                    model_type=node.model_type,
                                    discovery_mode="v4_only",
                                )
                            except Exception as e:
                                failed_models.append(str(meta_path))
                                error_type = type(e).__name__
                                failed_reasons.append(f"{meta_path}: {error_type} - {str(e)}")
                                logger.error(
                                    "model_discovery_v4_metadata_failed",
                                    model_file=str(meta_path),
                                    error=str(e),
                                    error_type=error_type,
                                    discovery_mode="v4_only",
                                    exc_info=True,
                                    message="Failed to load v4 ensemble from metadata; continuing with other v4 metadata files",
                                )
        except Exception as e:
            logger.critical(
                "model_discovery_critical_error",
                error=str(e),
                discovery_mode="v4_only",
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
                discovery_mode="v4_only",
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
    
    _STRICT_ARTIFACTS = frozenset({
        "entry_meta", "exit_model", "regime_model",
        "entry_base", "exit_base", "entry_scaler", "exit_scaler",
    })

    def _find_model_files(self) -> List[Path]:
        """Find all model files in storage directory. Excludes strict robust-ensemble artifacts in xgboost."""
        model_files = []
        if self.model_dir.exists():
            model_files.extend(self.model_dir.glob("*.pkl"))
            model_files.extend(self.model_dir.glob("*.h5"))
            model_files.extend(self.model_dir.glob("*.onnx"))
        for subdir in ["custom", "xgboost", "lightgbm", "random_forest", "lstm", "transformer"]:
            subdir_path = self.model_dir / subdir
            if subdir_path.exists():
                for ext in ("*.pkl", "*.h5", "*.onnx", "*.pt", "*.pth"):
                    for p in subdir_path.glob(ext):
                        if subdir == "xgboost" and p.stem in self._STRICT_ARTIFACTS:
                            continue
                        model_files.append(p)
        return model_files
    
    async def _load_model_from_path(self, model_path: Path) -> Optional[MCPModelNode]:
        """Load model node from file path."""
        
        # Determine model type from path and metadata
        model_type = self._detect_model_type(model_path)

        if model_type == "xgboost":
            from agent.models.xgboost_node import XGBoostNode
            return await XGBoostNode.load_from_file(model_path)
        elif model_type == "lightgbm":
            from agent.models.lightgbm_node import LightGBMNode
            return await LightGBMNode.load_from_file(model_path)
        elif model_type == "random_forest":
            from agent.models.random_forest_node import RandomForestNode
            return await RandomForestNode.load_from_file(model_path)
        elif model_type == "lstm":
            from agent.models.lstm_node import LSTMNode
            return await LSTMNode.load_from_file(model_path)
        elif model_type == "transformer":
            from agent.models.transformer_node import TransformerNode
            return await TransformerNode.load_from_file(model_path)
        else:
            logger.warning(
                "model_discovery_unknown_type",
                model_path=str(model_path),
                detected_type=model_type
            )
            return None
    
    def _detect_model_type(self, model_path: Path) -> str:
        """Detect model type from path and metadata."""
        
        # Check parent directory name
        parent_dir = model_path.parent.name
        if parent_dir in ["xgboost", "lightgbm", "random_forest", "lstm", "transformer"]:
            return parent_dir
        
        # Check metadata file
        metadata_path = model_path.parent / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                    return metadata.get("model_type", "unknown")
            except Exception:
                pass
        
        # Check filename
        filename = model_path.name.lower()
        if "xgboost" in filename:
            return "xgboost"
        elif "lightgbm" in filename or "lgb" in filename:
            return "lightgbm"
        elif "random_forest" in filename or "rf" in filename:
            return "random_forest"
        elif "lstm" in filename:
            return "lstm"
        elif "transformer" in filename:
            return "transformer"
        
        # Default: try to load as pickle and detect
        try:
            with open(model_path, "rb") as f:
                model = pickle.load(f)
                model_type = type(model).__name__.lower()
                
                if "xgboost" in model_type:
                    return "xgboost"
                elif "lightgbm" in model_type or "lgb" in model_type:
                    return "lightgbm"
                elif "randomforest" in model_type or "forest" in model_type:
                    return "random_forest"
        except Exception:
            pass
        
        return "unknown"

