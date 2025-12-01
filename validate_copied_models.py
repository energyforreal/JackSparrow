"""Validate the copied model files."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from scripts.validate_model_files import validate_all_models, generate_report

def main():
    """Validate copied models."""
    models_dir = Path("agent/model_storage")
    
    print("=" * 60)
    print("Validating Copied Models")
    print("=" * 60)
    print()
    
    results = validate_all_models(models_dir=models_dir, models_path=None)
    
    print(f"\n{'='*60}")
    print(f"Validation Summary")
    print(f"{'='*60}")
    print(f"Total files: {results['total']}")
    print(f"Valid XGBoost models: {results['valid_count']} ✅")
    print(f"Invalid/Corrupted: {results['invalid_count']} ❌")
    
    if results['valid']:
        print(f"\n✅ Valid Models:")
        for model_info in results['valid']:
            print(f"  - {Path(model_info['path']).name}")
    
    if results['invalid']:
        print(f"\n❌ Invalid Models:")
        for model_info in results['invalid']:
            print(f"  - {Path(model_info['path']).name}: {model_info.get('error', 'Unknown error')}")
    
    return results['invalid_count'] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)