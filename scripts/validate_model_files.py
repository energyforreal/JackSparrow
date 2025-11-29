#!/usr/bin/env python3
"""
Model file validation script.

Validates all model files in storage directories for integrity,
checks for corruption, and generates reports.
"""

import sys
import pickle
import hashlib
import types
from pathlib import Path
from typing import List, Dict, Tuple
import structlog
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = structlog.get_logger()


def _ensure_pickle_compatibility():
    """Register compatibility shims for legacy-pickled XGBoost models."""
    try:
        from xgboost import XGBClassifier
    except ImportError as e:
        logger.warning(
            "xgboost_not_available",
            error=str(e),
            message="XGBoost not installed - XGBClassifier compatibility shim cannot be registered. "
                   "Install xgboost package to validate XGBoost models."
        )
        return
    
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


# Register XGBClassifier compatibility shim at module import time
# This ensures pickle.load() can find the module when unpickling legacy models
_ensure_pickle_compatibility()


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def validate_pickle_file(file_path: Path) -> Tuple[bool, str, Dict]:
    """Validate a pickle file.
    
    Returns:
        Tuple of (is_valid, error_message, file_info)
    """
    file_info = {
        "path": str(file_path),
        "exists": False,
        "size": 0,
        "is_valid": False,
        "checksum": None,
        "error": None,
        "magic_bytes": None,
        "pickle_protocol": None,
    }
    
    if not file_path.exists():
        return False, "File does not exist", file_info
    
    file_info["exists"] = True
    file_info["size"] = file_path.stat().st_size
    
    if file_info["size"] == 0:
        return False, "File is empty", {**file_info, "error": "Empty file"}
    
    if file_info["size"] < 100:
        return False, "File is suspiciously small (< 100 bytes)", {**file_info, "error": "Too small"}
    
    # Check magic bytes
    try:
        with open(file_path, "rb") as f:
            magic_bytes = f.read(4)
            file_info["magic_bytes"] = magic_bytes.hex()
            
            if not magic_bytes.startswith(b'\x80'):
                return False, "File does not appear to be a valid pickle file", {
                    **file_info,
                    "error": f"Invalid magic bytes: {magic_bytes.hex()}"
                }
            
            # Get pickle protocol version
            if len(magic_bytes) > 1:
                file_info["pickle_protocol"] = magic_bytes[1]
    except Exception as e:
        return False, f"Error reading file header: {e}", {**file_info, "error": str(e)}
    
    # Ensure compatibility shims are loaded BEFORE attempting to load pickle
    # This must happen before pickle.load() to handle legacy XGBClassifier module references
    _ensure_pickle_compatibility()
    
    # Try to load the pickle file
    try:
        with open(file_path, "rb") as f:
            obj = pickle.load(f)
        
        # CRITICAL: Check if object is numpy array (corrupted model)
        if isinstance(obj, np.ndarray):
            error_msg = (
                f"Model file contains numpy array instead of XGBoost model. "
                f"Array shape: {obj.shape}, dtype: {obj.dtype}. "
                f"Sample values: {obj.flat[:5] if obj.size > 0 else 'empty'}. "
                f"This indicates the model file was saved incorrectly - it contains feature names "
                f"instead of the trained model."
            )
            return False, error_msg, {
                **file_info,
                "error": "Model is numpy array, not XGBoost model",
                "object_type": "numpy.ndarray",
                "array_shape": str(obj.shape),
                "array_dtype": str(obj.dtype)
            }
        
        # Check if it's an XGBoost model
        try:
            from xgboost import XGBClassifier
            is_xgboost = isinstance(obj, XGBClassifier)
        except ImportError:
            is_xgboost = False
        
        if is_xgboost:
            # Validate model has required methods
            if not hasattr(obj, 'predict'):
                return False, "XGBoost model missing 'predict' method", {
                    **file_info,
                    "error": "Missing predict method",
                    "object_type": type(obj).__name__
                }
            
            if not hasattr(obj, 'predict_proba'):
                return False, "XGBoost model missing 'predict_proba' method", {
                    **file_info,
                    "error": "Missing predict_proba method",
                    "object_type": type(obj).__name__
                }
            
            # Test prediction with dummy data
            try:
                dummy_X = np.random.rand(1, 49)  # 49 features
                prediction = obj.predict(dummy_X)
                proba = obj.predict_proba(dummy_X)
                file_info["prediction_test"] = "passed"
                file_info["prediction_shape"] = str(prediction.shape)
                file_info["proba_shape"] = str(proba.shape)
            except Exception as pred_e:
                return False, f"Model prediction test failed: {pred_e}", {
                    **file_info,
                    "error": f"Prediction test failed: {str(pred_e)}",
                    "object_type": type(obj).__name__
                }
            
            file_info["object_type"] = "XGBClassifier"
            file_info["model_valid"] = True
        else:
            # Not an XGBoost model, but might be valid pickle
            file_info["object_type"] = type(obj).__name__
            file_info["model_valid"] = False
            file_info["warning"] = f"File contains {type(obj).__name__}, not XGBoost model"
        
        # If it's a valid XGBoost model, mark as valid
        # Otherwise, mark as invalid (even if pickle loads successfully)
        if file_info.get("model_valid"):
            file_info["checksum"] = calculate_checksum(file_path)
            file_info["is_valid"] = True
            return True, "File is valid XGBoost model", file_info
        else:
            # Not a valid model, mark as invalid
            return False, f"File does not contain valid XGBoost model (contains {file_info.get('object_type', 'unknown')})", {
                **file_info,
                "error": f"Not a valid XGBoost model: {file_info.get('warning', 'Unknown type')}"
            }
        
    except ModuleNotFoundError as e:
        error_msg = str(e)
        # Check if it's the XGBClassifier module issue
        if "XGBClassifier" in error_msg:
            # Try to ensure compatibility shim is registered and retry
            _ensure_pickle_compatibility()
            try:
                with open(file_path, "rb") as f:
                    obj = pickle.load(f)
                file_info["checksum"] = calculate_checksum(file_path)
                file_info["is_valid"] = True
                return True, "File is valid (loaded after shim registration)", file_info
            except Exception as retry_e:
                return False, f"Module not found (XGBClassifier shim failed): {error_msg}. Retry error: {retry_e}", {
                    **file_info,
                    "error": f"ModuleNotFoundError: {error_msg}"
                }
        return False, f"Module not found: {error_msg}", {
            **file_info,
            "error": f"ModuleNotFoundError: {error_msg}"
        }
    except pickle.UnpicklingError as e:
        error_msg = str(e)
        if "invalid load key" in error_msg.lower():
            return False, f"File is corrupted (invalid pickle data): {error_msg}", {
                **file_info,
                "error": f"Corrupted pickle: {error_msg}"
            }
        return False, f"Unpickling error: {error_msg}", {**file_info, "error": error_msg}
    except Exception as e:
        return False, f"Error loading file: {type(e).__name__}: {e}", {
            **file_info,
            "error": f"{type(e).__name__}: {str(e)}"
        }


def find_model_files(base_dir: Path) -> List[Path]:
    """Find all model files in directory tree."""
    model_files = []
    
    if not base_dir.exists():
        return model_files
    
    # Common model file extensions
    extensions = ['.pkl', '.joblib', '.h5', '.keras', '.onnx']
    
    for ext in extensions:
        model_files.extend(base_dir.rglob(f"*{ext}"))
    
    return sorted(model_files)


def validate_all_models(models_dir: Path = None, models_path: Path = None) -> Dict:
    """Validate all model files in storage directories.
    
    Args:
        models_dir: Directory for model discovery (e.g., agent/model_storage)
        models_path: Specific model file path (e.g., models/xgboost_BTCUSD_15m.pkl)
    
    Returns:
        Dictionary with validation results
    """
    results = {
        "valid": [],
        "invalid": [],
        "total": 0,
        "valid_count": 0,
        "invalid_count": 0,
    }
    
    files_to_check = []
    
    # Add MODEL_PATH if specified
    if models_path:
        models_path_obj = Path(models_path)
        if models_path_obj.exists():
            files_to_check.append(models_path_obj)
    
    # Add files from MODEL_DIR
    if models_dir:
        models_dir_obj = Path(models_dir)
        if models_dir_obj.exists():
            files_to_check.extend(find_model_files(models_dir_obj))
    
    # Remove duplicates
    files_to_check = list(set(files_to_check))
    results["total"] = len(files_to_check)
    
    print(f"\n{'='*60}")
    print(f"Validating {results['total']} model file(s)...")
    print(f"{'='*60}\n")
    
    for file_path in files_to_check:
        is_valid, message, file_info = validate_pickle_file(file_path)
        
        if is_valid:
            results["valid"].append(file_info)
            results["valid_count"] += 1
            model_status = ""
            if file_info.get("model_valid"):
                model_status = " [XGBoost model ✓]"
            elif file_info.get("object_type") == "numpy.ndarray":
                model_status = " [CORRUPTED: numpy array]"
            print(f"✅ {file_path.name}: {message} ({file_info['size']:,} bytes){model_status}")
        else:
            results["invalid"].append(file_info)
            results["invalid_count"] += 1
            error_detail = ""
            if file_info.get("error"):
                error_detail = f" - {file_info['error']}"
            print(f"❌ {file_path.name}: {message}{error_detail}")
    
    return results


def generate_report(results: Dict, output_file: Path = None):
    """Generate validation report."""
    report_lines = [
        "# Model File Validation Report",
        "",
        f"Generated: {Path.cwd()}",
        "",
        f"## Summary",
        f"- Total files: {results['total']}",
        f"- Valid files: {results['valid_count']}",
        f"- Invalid files: {results['invalid_count']}",
        "",
    ]
    
    if results["valid"]:
        report_lines.append("## Valid Files")
        report_lines.append("")
        for file_info in results["valid"]:
            report_lines.append(f"- `{file_info['path']}`")
            report_lines.append(f"  - Size: {file_info['size']:,} bytes")
            if file_info.get("checksum"):
                report_lines.append(f"  - SHA256: {file_info['checksum']}")
            report_lines.append("")
    
    if results["invalid"]:
        report_lines.append("## Invalid Files")
        report_lines.append("")
        for file_info in results["invalid"]:
            report_lines.append(f"- `{file_info['path']}`")
            report_lines.append(f"  - Size: {file_info['size']:,} bytes")
            if file_info.get("error"):
                report_lines.append(f"  - Error: {file_info['error']}")
            if file_info.get("magic_bytes"):
                report_lines.append(f"  - Magic bytes: {file_info['magic_bytes']}")
            report_lines.append("")
    
    report_text = "\n".join(report_lines)
    
    if output_file:
        output_file.write_text(report_text)
        print(f"\n📄 Report saved to: {output_file}")
    else:
        print("\n" + report_text)


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv(dotenv_path=project_root / ".env")
    
    # Get paths from environment or use defaults
    models_dir = os.getenv("MODEL_DIR", "./agent/model_storage")
    model_path = os.getenv("MODEL_PATH", None)
    
    # Validate all models
    results = validate_all_models(
        models_dir=Path(models_dir) if models_dir else None,
        models_path=Path(model_path) if model_path else None
    )
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Validation Summary")
    print(f"{'='*60}")
    print(f"Total files: {results['total']}")
    print(f"Valid: {results['valid_count']} ✅")
    print(f"Invalid: {results['invalid_count']} ❌")
    
    # Generate report
    report_path = project_root / "logs" / "model_validation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(results, report_path)
    
    # Exit with error code if invalid files found
    if results["invalid_count"] > 0:
        print(f"\n⚠️  Warning: {results['invalid_count']} invalid file(s) found!")
        sys.exit(1)
    else:
        print("\n✅ All model files are valid!")
        sys.exit(0)

