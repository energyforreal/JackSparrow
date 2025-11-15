"""
Model discovery service.

Automatically discovers and registers ML models from storage directory.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import pickle

from agent.core.config import settings
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.mcp_model_node import MCPModelNode


class ModelDiscovery:
    """Model discovery service."""
    
    def __init__(self, registry: MCPModelRegistry):
        """Initialize model discovery."""
        self.registry = registry
        self.model_dir = Path(settings.model_dir)
        self.model_path = settings.model_path
    
    async def discover_models(self) -> List[str]:
        """Discover and register models."""
        
        discovered_models = []
        
        # Option 1: Load production model from MODEL_PATH
        if self.model_path:
            model_file = Path(self.model_path)
            if model_file.exists():
                try:
                    model_node = await self._load_model_from_path(model_file)
                    if model_node:
                        self.registry.register_model(model_node)
                        discovered_models.append(model_node.model_name)
                except Exception as e:
                    print(f"Error loading model from {model_file}: {e}")
        
        # Option 2: Discover models from MODEL_DIR
        if settings.model_discovery_enabled and self.model_dir.exists():
            for model_file in self._find_model_files():
                try:
                    model_node = await self._load_model_from_path(model_file)
                    if model_node:
                        self.registry.register_model(model_node)
                        discovered_models.append(model_node.model_name)
                except Exception as e:
                    print(f"Error loading model from {model_file}: {e}")
        
        return discovered_models
    
    def _find_model_files(self) -> List[Path]:
        """Find all model files in storage directory."""
        
        model_files = []
        
        # Search in subdirectories
        for subdir in ["custom", "xgboost", "lstm", "transformer"]:
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
            print(f"Unknown model type for {model_path}")
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

