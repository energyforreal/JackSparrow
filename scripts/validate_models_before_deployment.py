#!/usr/bin/env python3
"""
Pre-deployment model validation script.

Validates all model files before deployment to ensure they're valid XGBoost models.
This script should be run before deploying models to production.
"""

import sys
import os
from pathlib import Path
from typing import List, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.validate_model_files import validate_all_models, generate_report


def validate_models_for_deployment() -> bool:
    """Validate all models before deployment.
    
    Returns:
        True if all models are valid, False otherwise
    """
    print("=" * 60)
    print("Pre-Deployment Model Validation")
    print("=" * 60)
    print()
    
    # Get model paths from environment or use defaults
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
    print(f"Valid XGBoost models: {results['valid_count']} ✅")
    print(f"Invalid/Corrupted: {results['invalid_count']} ❌")
    
    # Check for corrupted models (numpy arrays)
    corrupted_count = sum(
        1 for f in results["invalid"]
        if f.get("object_type") == "numpy.ndarray"
    )
    
    if corrupted_count > 0:
        print(f"\n⚠️  WARNING: {corrupted_count} model file(s) contain numpy arrays instead of trained models!")
        print("   These files need to be regenerated using scripts/train_models.py")
    
    # Generate detailed report
    report_path = project_root / "logs" / "pre_deployment_validation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(results, report_path)
    
    # Exit with error code if invalid files found
    if results["invalid_count"] > 0:
        print(f"\n❌ DEPLOYMENT BLOCKED: {results['invalid_count']} invalid model file(s) found!")
        print(f"   Please fix model files before deployment.")
        print(f"   See report: {report_path}")
        return False
    else:
        print("\n✅ All model files are valid! Ready for deployment.")
        return True


if __name__ == "__main__":
    success = validate_models_for_deployment()
    sys.exit(0 if success else 1)
