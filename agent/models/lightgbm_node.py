"""LightGBM model node implementation."""

from typing import Dict, Any
from pathlib import Path
import pickle

from agent.models.xgboost_node import XGBoostNode  # Similar implementation


class LightGBMNode(XGBoostNode):
    """LightGBM model node (similar to XGBoost)."""
    
    def __init__(self, model_path: Path):
        """Initialize LightGBM node."""
        super().__init__(model_path)
        self.model_type = "lightgbm"

