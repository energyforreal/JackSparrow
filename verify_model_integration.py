"""Verify model integration - can models be loaded and used?"""
import asyncio
import sys
from pathlib import Path
import numpy as np

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent.models.xgboost_node import XGBoostNode

async def test_model_loading():
    """Test loading one model to verify integration works."""
    model_path = Path("agent/model_storage/xgboost/xgboost_classifier_BTCUSD_15m.pkl")
    
    print("Testing model loading...")
    print(f"Model path: {model_path}")
    print(f"Exists: {model_path.exists()}")
    
    if not model_path.exists():
        print("ERROR: Model file not found!")
        return False
    
    try:
        # Load the model
        node = await XGBoostNode.load_from_file(model_path)
        print(f"✓ Model loaded: {node.model_name}")
        print(f"  Type: {node.model_type}")
        print(f"  Version: {node.model_version}")
        print(f"  Health: {node.health_status}")
        
        # Test prediction
        print("\nTesting prediction...")
        sample_features = np.array([[0.5] * 49])  # 49 features (typical)
        
        from agent.models.mcp_model_node import MCPModelRequest
        request = MCPModelRequest(
            request_id="test_001",
            features=list(sample_features[0]),
            context={"feature_names": [f"feature_{i}" for i in range(49)]},
            require_explanation=False
        )
        
        response = await node.predict(request)
        print(f"✓ Prediction successful")
        print(f"  Prediction: {response.predictions[0].prediction:.4f}")
        print(f"  Confidence: {response.predictions[0].confidence:.4f}")
        
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_model_loading())
    sys.exit(0 if success else 1)