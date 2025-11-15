"""Random Forest model node implementation."""

from typing import Dict, Any
from pathlib import Path

from agent.models.xgboost_node import XGBoostNode  # Similar implementation


class RandomForestNode(XGBoostNode):
    """Random Forest model node (similar to XGBoost)."""
    
    def __init__(self, model_path: Path):
        """Initialize Random Forest node."""
        super().__init__(model_path)
        self.model_type = "random_forest"

