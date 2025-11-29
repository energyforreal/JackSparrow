"""Attempt to recover corrupted model files.

This script tries multiple strategies to recover corrupted pickle files,
including different protocols, encodings, and error handling modes.
"""

import pickle
import sys
import json
from pathlib import Path
from typing import Optional, Any, List, Dict
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def attempt_recovery(file_path: Path) -> Dict[str, Any]:
    """Try multiple strategies to recover a corrupted model file.
    
    Args:
        file_path: Path to the corrupted model file
        
    Returns:
        Dictionary with recovery status and results
    """
    result = {
        "file": str(file_path),
        "strategies_tried": [],
        "success": False,
        "recovered_model": None,
        "error": None,
    }
    
    strategies = [
        {
            "name": "standard_protocol",
            "func": lambda f: pickle.load(f),
            "description": "Standard pickle.load()",
        },
        {
            "name": "latin1_encoding",
            "func": lambda f: pickle.load(f, encoding="latin1"),
            "description": "Pickle with latin1 encoding",
        },
        {
            "name": "bytes_encoding",
            "func": lambda f: pickle.load(f, encoding="bytes"),
            "description": "Pickle with bytes encoding",
        },
        {
            "name": "errors_ignore",
            "func": lambda f: pickle.load(f, errors="ignore"),
            "description": "Pickle with errors='ignore'",
        },
    ]
    
    # Try pickle5 if available
    try:
        import pickle5
        
        strategies.append({
            "name": "pickle5_protocol",
            "func": lambda f: pickle5.load(f),
            "description": "Pickle5 protocol (newer)",
        })
    except ImportError:
        pass
    
    for strategy in strategies:
        try:
            with open(file_path, "rb") as f:
                recovered = strategy["func"](f)
                
                # Validate that we got something reasonable
                if recovered is not None:
                    result["strategies_tried"].append({
                        "name": strategy["name"],
                        "status": "success",
                        "description": strategy["description"],
                    })
                    result["success"] = True
                    result["recovered_model"] = recovered
                    result["successful_strategy"] = strategy["name"]
                    return result
                else:
                    result["strategies_tried"].append({
                        "name": strategy["name"],
                        "status": "failed",
                        "error": "Result is None",
                        "description": strategy["description"],
                    })
        except Exception as e:
            error_msg = str(e)
            result["strategies_tried"].append({
                "name": strategy["name"],
                "status": "failed",
                "error": error_msg[:100],  # Truncate long errors
                "description": strategy["description"],
            })
    
    result["error"] = "All recovery strategies failed"
    return result


def validate_model(model: Any, expected_type: Optional[str] = None) -> bool:
    """Validate that recovered object is a valid model.
    
    Args:
        model: The recovered model object
        expected_type: Expected model type (e.g., 'xgboost', 'lightgbm', 'random_forest')
        
    Returns:
        True if model appears valid, False otherwise
    """
    if model is None:
        return False
    
    # Check for common model attributes
    has_predict = hasattr(model, "predict")
    has_predict_proba = hasattr(model, "predict_proba") or hasattr(model, "predict_proba")
    
    if not has_predict:
        return False
    
    # Type-specific checks
    if expected_type == "xgboost":
        # Check for XGBoost-specific attributes
        return has_predict and (hasattr(model, "feature_importances_") or hasattr(model, "get_booster"))
    elif expected_type == "lightgbm":
        return has_predict and hasattr(model, "feature_importance")
    elif expected_type == "random_forest":
        return has_predict and hasattr(model, "n_estimators")
    
    # Generic check: if it has predict, it's probably a model
    return has_predict


def main():
    """Main recovery process."""
    # Define corrupted files based on audit report
    corrupted_files = [
        {
            "path": Path("agent/model_storage/random_forest/randomforest_BTCUSD_4h_production_20251014_125258.pkl"),
            "type": "random_forest",
        },
        {
            "path": Path("agent/model_storage/lightgbm/lightgbm_BTCUSD_4h_production_20251014_115655.pkl"),
            "type": "lightgbm",
        },
        {
            "path": Path("agent/model_storage/xgboost/xgboost_BTCUSD_4h_production_20251014_114541.pkl"),
            "type": "xgboost",
        },
    ]
    
    print("=" * 70)
    print("  Model Recovery Tool")
    print("=" * 70)
    print()
    
    # Create backup directory
    backup_dir = project_root / "models" / "backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    print(f"Backup directory: {backup_dir}\n")
    
    results = []
    
    for file_info in corrupted_files:
        file_path = project_root / file_info["path"]
        model_type = file_info["type"]
        
        if not file_path.exists():
            print(f"⚠️  File not found: {file_path}")
            print()
            continue
        
        print(f"Attempting recovery: {file_path.name}")
        print(f"  Type: {model_type}")
        print(f"  Size: {file_path.stat().st_size:,} bytes")
        print()
        
        # Attempt recovery
        recovery_result = attempt_recovery(file_path)
        results.append({**recovery_result, "model_type": model_type})
        
        if recovery_result["success"]:
            print(f"✓ Recovery successful using: {recovery_result['successful_strategy']}")
            
            # Validate model
            if validate_model(recovery_result["recovered_model"], model_type):
                print(f"✓ Model validation passed")
                
                # Create backup
                backup_path = backup_dir / file_path.name
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                
                import shutil
                shutil.copy2(file_path, backup_path)
                print(f"✓ Original file backed up to: {backup_path}")
                
                # Save recovered model
                try:
                    with open(file_path, "wb") as f:
                        pickle.dump(
                            recovery_result["recovered_model"],
                            f,
                            protocol=pickle.HIGHEST_PROTOCOL,
                        )
                    print(f"✓ Recovered model saved to: {file_path}")
                except Exception as e:
                    print(f"✗ Failed to save recovered model: {e}")
            else:
                print(f"⚠️  Model validation failed - recovered object may not be a valid model")
        else:
            print(f"✗ Recovery failed: {recovery_result['error']}")
            print(f"  Strategies tried: {len(recovery_result['strategies_tried'])}")
        
        print()
    
    # Summary
    print("=" * 70)
    print("  Recovery Summary")
    print("=" * 70)
    print()
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    print(f"Total files processed: {len(results)}")
    print(f"Successfully recovered: {len(successful)}")
    print(f"Failed to recover: {len(failed)}")
    print()
    
    if successful:
        print("Successfully recovered files:")
        for result in successful:
            print(f"  ✓ {Path(result['file']).name} ({result['model_type']})")
        print()
    
    if failed:
        print("Failed to recover files:")
        for result in failed:
            print(f"  ✗ {Path(result['file']).name} ({result['model_type']})")
            print(f"    Error: {result.get('error', 'Unknown error')}")
        print()
        print("Recommendation: Re-train these models or remove them from model storage")
    
    # Save recovery report
    report_path = backup_dir / "recovery_report.json"
    with open(report_path, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "results": [
                    {
                        **r,
                        "recovered_model": None,  # Don't serialize models
                    }
                    for r in results
                ],
            },
            f,
            indent=2,
        )
    print(f"Recovery report saved to: {report_path}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nRecovery interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError during recovery: {e}")
        import traceback
        
        traceback.print_exc()
        sys.exit(1)
