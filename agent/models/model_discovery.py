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
    
    async def discover_models(self) -> List[str]:
        """Discover and register models.
        
        Returns:
            List of successfully discovered model names
            
        Note:
            This method will continue discovery even if individual models fail.
            Errors are logged but do not crash the agent.
        """
        
        discovered_models = []
        failed_models = []
        
        try:
            # Option 1: Load production model from MODEL_PATH
            if self.model_path:
                model_file = Path(self.model_path)
                if model_file.exists():
                    try:
                        model_node = await self._load_model_from_path(model_file)
                        if model_node:
                            self.registry.register_model(model_node)
                            discovered_models.append(model_node.model_name)
                            logger.info(
                                "model_discovered",
                                model_name=model_node.model_name,
                                model_path=str(model_file)
                            )
                        else:
                            failed_models.append(str(model_file))
                    except Exception as e:
                        failed_models.append(str(model_file))
                        logger.error(
                            "model_discovery_load_failed",
                            model_file=str(model_file),
                            error=str(e),
                            exc_info=True,
                            message="Model discovery will continue with other models"
                        )
                else:
                    logger.warning(
                        "model_path_not_found",
                        model_path=str(model_file),
                        message="MODEL_PATH specified but file does not exist"
                    )
            
            # Option 2: Discover models from MODEL_DIR
            if settings.model_discovery_enabled:
                try:
                    if not self.model_dir.exists():
                        logger.warning(
                            "model_dir_not_found",
                            model_dir=str(self.model_dir),
                            message="MODEL_DIR does not exist, skipping discovery"
                        )
                    else:
                        model_files = self._find_model_files()
                        logger.info(
                            "model_discovery_scanning",
                            model_dir=str(self.model_dir),
                            files_found=len(model_files)
                        )
                        
                        for model_file in model_files:
                            try:
                                model_node = await self._load_model_from_path(model_file)
                                if model_node:
                                    self.registry.register_model(model_node)
                                    discovered_models.append(model_node.model_name)
                                    logger.info(
                                        "model_discovered",
                                        model_name=model_node.model_name,
                                        model_path=str(model_file)
                                    )
                                else:
                                    failed_models.append(str(model_file))
                            except Exception as e:
                                failed_models.append(str(model_file))
                                logger.error(
                                    "model_discovery_load_failed",
                                    model_file=str(model_file),
                                    error=str(e),
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
        
        # Log summary
        if discovered_models:
            logger.info(
                "model_discovery_complete",
                discovered_count=len(discovered_models),
                failed_count=len(failed_models),
                models=discovered_models
            )
        else:
            logger.warning(
                "model_discovery_no_models",
                failed_count=len(failed_models),
                message="No models were successfully discovered"
            )
        
        return discovered_models
    
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
                # Find .pkl, .h5, .onnx files
                model_files.extend(subdir_path.glob("*.pkl"))
                model_files.extend(subdir_path.glob("*.h5"))
                model_files.extend(subdir_path.glob("*.onnx"))
        
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

