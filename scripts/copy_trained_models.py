#!/usr/bin/env python3
"""Copy trained models from Downloads to model storage directory."""
from pathlib import Path
import shutil
import sys

def main():
    """Copy trained models and verify."""
    source_dir = Path(r"c:\Users\lohit\Downloads\trained_models_20251130_120238")
    dest_dir = Path("agent/model_storage/xgboost")
    
    # Verify source exists
    if not source_dir.exists():
        print(f"ERROR: Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1
    
    # Create destination
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Find model files
    model_files = sorted(source_dir.glob("*.pkl"))
    if not model_files:
        print(f"ERROR: No .pkl files found in {source_dir}", file=sys.stderr)
        return 1
    
    print(f"Copying {len(model_files)} model files...", file=sys.stderr)
    
    # Copy files
    copied = 0
    for model_file in model_files:
        dest_path = dest_dir / model_file.name
        try:
            shutil.copy2(model_file, dest_path)
            size_kb = dest_path.stat().st_size / 1024
            print(f"Copied: {model_file.name} ({size_kb:.1f} KB)", file=sys.stderr)
            copied += 1
        except Exception as e:
            print(f"ERROR copying {model_file.name}: {e}", file=sys.stderr)
            return 1
    
    # Verify all files copied
    dest_files = list(dest_dir.glob("*.pkl"))
    if len(dest_files) != len(model_files):
        print(f"ERROR: Expected {len(model_files)} files, found {len(dest_files)}", file=sys.stderr)
        return 1
    
    print(f"Successfully copied {copied} model files to {dest_dir.absolute()}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())