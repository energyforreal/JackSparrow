"""Inspect model pickle files to understand their structure."""
import pickle
from pathlib import Path
import sys
import types
import numpy as np
from xgboost import XGBClassifier

# Apply compatibility shim (same as in xgboost_node.py)
def _ensure_pickle_compatibility():
    """Register compatibility shims for legacy-pickled XGBoost models."""
    module_name = "XGBClassifier"
    if module_name in sys.modules:
        return

    shim = types.ModuleType(module_name)
    def _module_getattr(name: str):
        if name == "XGBClassifier":
            return XGBClassifier
        if hasattr(np, name):
            return getattr(np, name)
        raise AttributeError(f"module '{module_name}' has no attribute '{name}'")
    shim.__getattr__ = _module_getattr
    shim.XGBClassifier = XGBClassifier
    shim.dtype = np.dtype
    shim.ndarray = np.ndarray
    sys.modules[module_name] = shim

_ensure_pickle_compatibility()

def inspect_model_file(model_path: Path):
    """Inspect a model pickle file."""
    print(f"\n{'='*60}")
    print(f"Inspecting: {model_path}")
    print(f"{'='*60}")
    
    try:
        with open(model_path, 'rb') as f:
            obj = pickle.load(f)
        
        print(f"Type: {type(obj).__name__}")
        print(f"Module: {type(obj).__module__}")
        
        if isinstance(obj, np.ndarray):
            print(f"  Shape: {obj.shape}")
            print(f"  Dtype: {obj.dtype}")
            print(f"  First few values: {obj.flat[:5] if obj.size > 0 else 'empty'}")
        elif isinstance(obj, dict):
            print(f"  Dictionary with keys: {list(obj.keys())}")
            for key, value in obj.items():
                print(f"    {key}: {type(value).__name__}")
                if hasattr(value, 'predict'):
                    print(f"      -> Has predict method!")
        elif hasattr(obj, 'predict'):
            print(f"  Has predict method: ✓")
            print(f"  Has predict_proba: {hasattr(obj, 'predict_proba')}")
            print(f"  Model type appears valid")
        else:
            print(f"  Attributes: {[attr for attr in dir(obj) if not attr.startswith('_')][:10]}")
            
    except Exception as e:
        print(f"Error loading file: {e}")

if __name__ == "__main__":
    # Check models/ directory
    models_dir = Path("models")
    model_files = []
    
    if models_dir.exists():
        model_files.extend(models_dir.glob("xgboost*.pkl"))
        print(f"Found {len(model_files)} XGBoost model files in models/")
    
    # Check agent/model_storage/ directory
    model_storage_dir = Path("agent/model_storage")
    if model_storage_dir.exists():
        storage_files = list(model_storage_dir.rglob("*.pkl"))
        print(f"Found {len(storage_files)} pickle files in agent/model_storage/")
        model_files.extend(storage_files[:3])  # Add first 3 from storage
    
    if not model_files:
        print("No model files found!")
        exit(1)
    
    for model_file in model_files[:5]:  # Inspect first 5
        inspect_model_file(model_file)

