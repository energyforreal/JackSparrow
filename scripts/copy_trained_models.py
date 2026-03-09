#!/usr/bin/env python3
"""Copy the three production XGBoost models into agent/model_storage/xgboost.

This script is intended to be run locally on the host machine.
It will:
- Read the three trained XGBoost classifier models (15m, 1h, 4h) from the
  user's Downloads directory.
- Archive any existing XGBoost .pkl files in agent/model_storage/xgboost
  into an 'archive' subdirectory.
- Copy only the three target models into agent/model_storage/xgboost.

Docker deployments mount ./agent/model_storage into the agent container, so
once this script has run successfully, both local and Docker agents will
discover and use only these three models via ModelDiscovery.
"""

from pathlib import Path
import shutil
import sys
import pickle


# Windows Downloads directory containing the trained models
SOURCE_DIR = Path(r"C:\Users\lohit\Downloads\ML models Jacksparrow")

# Destination directory used by the agent (also mounted into Docker)
DEST_DIR = Path("agent/model_storage/xgboost")

# Exact filenames expected from the training pipeline
TARGET_MODEL_NAMES = {
    "xgboost_classifier_BTCUSD_15m.pkl",
    "xgboost_classifier_BTCUSD_1h.pkl",
    "xgboost_classifier_BTCUSD_4h.pkl",
}


def main() -> int:
    """Copy the three target models and archive older ones."""
    source_dir = SOURCE_DIR
    dest_dir = DEST_DIR
    archive_dir = dest_dir / "archive"

    print("=" * 70, file=sys.stderr)
    print("Copying production XGBoost models (15m, 1h, 4h)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Verify source exists
    if not source_dir.exists():
        print(f"ERROR: Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    # Create destination and archive directories
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Locate available target model files in the source directory
    available = {p.name: p for p in source_dir.glob("*.pkl") if p.name in TARGET_MODEL_NAMES}

    if not available:
        print(f"ERROR: None of the expected .pkl files were found in {source_dir}", file=sys.stderr)
        print("Expected files:", file=sys.stderr)
        for name in sorted(TARGET_MODEL_NAMES):
            print(f"  - {name}", file=sys.stderr)
        return 1

    missing = TARGET_MODEL_NAMES.difference(available.keys())
    if missing:
        print("WARNING: The following expected model files were NOT found in the source directory:", file=sys.stderr)
        for name in sorted(missing):
            print(f"  - {name}", file=sys.stderr)

    # Archive any existing .pkl files in the destination (older models)
    existing_models = list(dest_dir.glob("*.pkl"))
    if existing_models:
        print(f"\nArchiving {len(existing_models)} existing model file(s) from {dest_dir} ...", file=sys.stderr)
        for old_file in existing_models:
            try:
                target = archive_dir / old_file.name
                # If a file with the same name already exists in archive, add a suffix
                if target.exists():
                    target = archive_dir / f"{old_file.stem}.old{old_file.suffix}"
                shutil.move(str(old_file), str(target))
                print(f"  Archived: {old_file.name} -> {target.name}", file=sys.stderr)
            except Exception as exc:
                print(f"ERROR archiving {old_file}: {exc}", file=sys.stderr)
                return 1
    else:
        print("\nNo existing XGBoost model files to archive in dest dir.", file=sys.stderr)

    # Copy the available target models
    print("\nCopying target models into agent/model_storage/xgboost ...", file=sys.stderr)
    copied = 0
    for name in sorted(available.keys()):
        src_path = available[name]
        dest_path = dest_dir / name
        try:
            if dest_path.exists():
                # Move any pre-existing file with the same name into archive first
                backup = archive_dir / name
                shutil.move(str(dest_path), str(backup))
                print(f"  Existing file backed up: {dest_path.name} -> {backup.name}", file=sys.stderr)

            shutil.copy2(src_path, dest_path)
            size_kb = dest_path.stat().st_size / 1024
            print(f"  Copied: {name} ({size_kb:.1f} KB)", file=sys.stderr)
            copied += 1
        except Exception as exc:
            print(f"ERROR copying {name}: {exc}", file=sys.stderr)
            return 1

    if copied == 0:
        print("ERROR: No models were copied. See warnings above.", file=sys.stderr)
        return 1

    # Lightweight structural validation: ensure each copied file is a valid pickle
    # and appears to contain a model object with a predict() method (or a bundle
    # dict containing such a model under the 'model' key).
    print("\nValidating copied models...", file=sys.stderr)
    for name in sorted(available.keys()):
        dest_path = dest_dir / name
        if not dest_path.exists():
            continue
        try:
            with open(dest_path, "rb") as fh:
                obj = pickle.load(fh)
            # Handle bundle format created by some training scripts
            if isinstance(obj, dict) and "model" in obj:
                model_obj = obj["model"]
            else:
                model_obj = obj
            has_predict = hasattr(model_obj, "predict")
            if not has_predict:
                print(f"WARNING: {name} loaded but object has no 'predict' method (type={type(model_obj).__name__})", file=sys.stderr)
            else:
                print(f"  ✓ {name}: load OK, predict() available (type={type(model_obj).__name__})", file=sys.stderr)
        except Exception as exc:
            print(f"ERROR: Failed to validate {name}: {exc}", file=sys.stderr)
            return 1

    # Final verification: list models now present in dest_dir
    final_files = sorted(p.name for p in dest_dir.glob("*.pkl"))
    print("\nFinal models present in agent/model_storage/xgboost:", file=sys.stderr)
    for name in final_files:
        print(f"  - {name}", file=sys.stderr)

    print(f"\nSuccessfully copied {copied} model file(s) to {dest_dir.absolute()}", file=sys.stderr)
    print("Docker agents that mount ./agent/model_storage will now discover only these models.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())