"""
Embedding service.

Generates embeddings for decision contexts.
"""

from typing import Dict, Any, List
import json


class EmbeddingService:
    """Service for generating embeddings."""
    
    def __init__(self):
        """Initialize embedding service."""
        pass
    
    def generate_embedding(self, context: Dict[str, Any]) -> List[float]:
        """Generate embedding from context."""
        # Placeholder - would use sentence-transformers or similar
        # For now, return simple hash-based "embedding"
        context_str = json.dumps(context, sort_keys=True)
        return [float(hash(context_str) % 1000) / 1000.0] * 128  # 128-dim placeholder

