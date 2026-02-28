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
            message="Starting model discovery process"
        )
        
        try:
            # Option 1: Load production model from MODEL_PATH
            if self.model_path:
                model_file = Path(self.model_path)
                logger.debug(
                    "model_discovery_checking_path",
                    model_path=str(model_file),
                    exists=model_file.exists(),
                    absolute_path=str(model_file.resolve()) if model_file.exists() else None
                )
                if model_file.exists():
                    discovery_attempted = True
                    try:
                        logger.info(
                            "model_discovery_loading",
                            model_path=str(model_file)
                        )
                        model_node = await self._load_model_from_path(model_file)
                        if model_node:
                            # Check for duplicate model name
                            if model_node.model_name in loaded_model_names:
                                logger.warning(
                                    "model_discovery_duplicate_skipped",
                                    model_name=model_node.model_name,
                                    model_path=str(model_file),
                                    reason="Model with same name already loaded from MODEL_PATH (preferring MODEL_PATH over MODEL_DIR)"
                                )
                            else:
                                self._handle_discovered_model(model_node, discovered_models)
                                loaded_model_names.add(model_node.model_name)
                                logger.info(
                                    "model_discovered",
                                    model_name=model_node.model_name,
                                    model_path=str(model_file),
                                    model_type=model_node.model_type
                                )
                        else:
                            failed_models.append(str(model_file))
                            failed_reasons.append(f"{model_file}: unsupported model type or loader returned None")
                            logger.warning(
                                "model_discovery_load_returned_none",
                                model_file=str(model_file),
                                message="Model loader returned None - model type may not be supported"
                            )
                    except Exception as e:
                        failed_models.append(str(model_file))
                        error_type = type(e).__name__
                        failed_reasons.append(f"{model_file}: {error_type} - {str(e)}")
                        
                        # Special handling for corrupted/unpickling errors
                        if error_type == "UnpicklingError" or "pickle" in str(e).lower() or "unpickling" in str(e).lower():
                            logger.error(
                                "model_discovery_corrupted_file",
                                model_file=str(model_file),
                                error=str(e),
                                error_type=error_type,
                                exc_info=True,
                                message="Model file appears to be corrupted or incompatible. Skipping this model and continuing discovery."
                            )
                        else:
                            logger.error(
                                "model_discovery_load_failed",
                                model_file=str(model_file),
                                error=str(e),
                                error_type=error_type,
                                exc_info=True,
                                message="Model discovery will continue with other models"
                            )
                else:
                    logger.warning(
                        "model_path_not_found",
                        model_path=str(model_file),
                        absolute_path=str(model_file.resolve()),
                        message="MODEL_PATH specified but file does not exist"
                    )
                    # If MODEL_PATH doesn't exist but discovery is enabled, we will attempt MODEL_DIR discovery
                    # Mark as attempted now if discovery is enabled
                    if settings.model_discovery_enabled:
                        discovery_attempted = True
            
            # Option 2: Discover models from MODEL_DIR
            if settings.model_discovery_enabled:
                try:
                    model_dir_abs = self.model_dir.resolve()
                    # Mark discovery as attempted when we check MODEL_DIR (even if it doesn't exist)
                    # This indicates we attempted to discover models
                    discovery_attempted = True
                    if not self.model_dir.exists():
                        logger.warning(
                            "model_dir_not_found",
                            model_dir=str(self.model_dir),
                            absolute_path=str(model_dir_abs),
                            message="MODEL_DIR does not exist, skipping discovery",
                            discovery_attempted=True
                        )
                    else:
                        model_files = self._find_model_files()
                        logger.info(
                            "model_discovery_scanning",
                            model_dir=str(self.model_dir),
                            absolute_path=str(model_dir_abs),
                            files_found=len(model_files),
                            file_list=[str(f) for f in model_files[:10]]  # Log first 10 files
                        )
                        
                        if not model_files:
                            logger.info(
                                "model_discovery_no_files",
                                model_dir=str(self.model_dir),
                                absolute_path=str(model_dir_abs),
                                discovery_attempted=True,
                                message="No model files found in MODEL_DIR. Discovery was attempted but directory is empty or contains no .pkl/.h5/.onnx files."
                            )
                        
                        for model_file in model_files:
                            try:
                                logger.debug(
                                    "model_discovery_loading_file",
                                    model_file=str(model_file),
                                    absolute_path=str(model_file.resolve())
                                )
                                
                                # Extract model name from file to check for duplicates BEFORE loading
                                # This avoids loading duplicate models unnecessarily
                                potential_model_name = model_file.stem
                                if potential_model_name in loaded_model_names:
                                    logger.debug(
                                        "model_discovery_duplicate_skipped_early",
                                        model_name=potential_model_name,
                                        model_path=str(model_file),
                                        reason="Model with same name already loaded - skipping to avoid duplicate load"
                                    )
                                    continue
                                
                                model_node = await self._load_model_from_path(model_file)
                                if model_node:
                                    # Check for duplicate model name (double-check after loading)
                                    if model_node.model_name in loaded_model_names:
                                        logger.warning(
                                            "model_discovery_duplicate_skipped",
                                            model_name=model_node.model_name,
                                            model_path=str(model_file),
                                            reason="Model with same name already loaded (duplicate detected)"
                                        )
                                    else:
                                        self._handle_discovered_model(model_node, discovered_models)
                                        loaded_model_names.add(model_node.model_name)
                                        logger.info(
                                            "model_discovered",
                                            model_name=model_node.model_name,
                                            model_path=str(model_file),
                                            model_type=model_node.model_type
                                        )
                                else:
                                    failed_models.append(str(model_file))
                                    failed_reasons.append(f"{model_file}: unsupported model type or loader returned None")
                                    logger.warning(
                                        "model_discovery_load_returned_none",
                                        model_file=str(model_file),
                                        message="Model loader returned None - model type may not be supported"
                                    )
                            except Exception as e:
                                failed_models.append(str(model_file))
                                error_type = type(e).__name__
                                failed_reasons.append(f"{model_file}: {error_type} - {str(e)}")
                                
                                # Special handling for corrupted/unpickling errors
                                if error_type == "UnpicklingError" or "pickle" in str(e).lower() or "unpickling" in str(e).lower():
                                    logger.error(
                                        "model_discovery_corrupted_file",
                                        model_file=str(model_file),
                                        error=str(e),
                                        error_type=error_type,
                                        exc_info=True,
                                        message="Model file appears to be corrupted or incompatible. Skipping this model and continuing discovery."
                                    )
                                else:
                                    logger.error(
                                        "model_discovery_load_failed",
                                        model_file=str(model_file),
                                        error=str(e),
                                        error_type=error_type,
                                        exc_info=True,
                                        message="Continuing with other models"
                                    )
                except Exception as e:
                    logger.error(
                        "model_discovery_scan_failed",
                        model_dir=str(self.model_dir),
                        error=str(e),
                        exc_info=True,
                        message="Model discovery scan failed, but agent will continue"
                    )
        except Exception as e:
            logger.critical(
                "model_discovery_critical_error",
                error=str(e),
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
    
    def _find_model_files(self) -> List[Path]:
        """Find all model files in storage directory."""
        
        model_files = []
        
        # Search in root model directory
        if self.model_dir.exists():
            # Find .pkl, .h5, .onnx files in root
            model_files.extend(self.model_dir.glob("*.pkl"))
            model_files.extend(self.model_dir.glob("*.h5"))
            model_files.extend(self.model_dir.glob("*.onnx"))
        
        # Search in subdirectories
        for subdir in ["custom", "xgboost", "lightgbm", "random_forest", "lstm", "transformer"]:
            subdir_path = self.model_dir / subdir
            if subdir_path.exists():
                # Find .pkl, .h5, .onnx, .pt, .pth files
                model_files.extend(subdir_path.glob("*.pkl"))
                model_files.extend(subdir_path.glob("*.h5"))
                model_files.extend(subdir_path.glob("*.onnx"))
                model_files.extend(subdir_path.glob("*.pt"))
                model_files.extend(subdir_path.glob("*.pth"))
        
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

