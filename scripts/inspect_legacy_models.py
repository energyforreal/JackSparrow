#!/usr/bin/env python3
"""Inspect existing XGBoost BTCUSD models and report their feature schema.

This is a diagnostic helper to understand the current models' expectations,
especially n_features_in_ and any bundled feature_cols metadata.

It does NOT modify any files.
"""

from pathlib import Path
import pickle
import sys
from typing import Any, Dict


def _load_model(path: Path) -> Any:
    """Load a model or bundle from a pickle file."""
    with open(path, "rb") as fh:
        obj = pickle.load(fh)
    # Some training flows save a bundle dict with a 'model' key
    if isinstance(obj, dict) and "model" in obj:
        return obj
    return obj


def _describe_bundle(obj: Any) -> Dict[str, Any]:
    """Extract key diagnostics from a model or bundle."""
    info: Dict[str, Any] = {}

    bundle = obj if isinstance(obj, dict) and "model" in obj else None
    model = bundle["model"] if bundle is not None else obj

    info["object_type"] = type(obj).__name__
    info["bundle_keys"] = list(bundle.keys()) if bundle is not None else []
    info["model_type"] = type(model).__name__

    # n_features_in_ if available
    n_features = getattr(model, "n_features_in_", None)
    info["n_features_in_"] = int(n_features) if n_features is not None else None

    # feature_cols from bundle, if present
    if bundle is not None and "feature_cols" in bundle:
        cols = bundle["feature_cols"]
        if isinstance(cols, (list, tuple)):
            info["feature_cols_count"] = len(cols)
            info["feature_cols_sample"] = list(cols[:10])
        else:
            info["feature_cols_count"] = None
            info["feature_cols_sample"] = None
    else:
        info["feature_cols_count"] = None
        info["feature_cols_sample"] = None

    return info


def main() -> int:
    base_dir = Path("agent/model_storage/xgboost")
    if not base_dir.exists():
        print(f"Directory not found: {base_dir}", file=sys.stderr)
        return 1

    model_files = sorted(base_dir.glob("xgboost_classifier_BTCUSD_*.pkl"))
    if not model_files:
        print(f"No BTCUSD classifier models found under {base_dir}", file=sys.stderr)
        return 1

    print(f"Inspecting {len(model_files)} BTCUSD XGBoost classifier model(s) in {base_dir}:\n")

    for path in model_files:
        print("=" * 80)
        print(f"File: {path}")
        print(f"Size: {path.stat().st_size:,} bytes")
        try:
            obj = _load_model(path)
            info = _describe_bundle(obj)
            print(f"  object_type       : {info['object_type']}")
            if info["bundle_keys"]:
                print(f"  bundle_keys       : {info['bundle_keys']}")
            print(f"  model_type        : {info['model_type']}")
            print(f"  n_features_in_    : {info['n_features_in_']}")
            print(f"  feature_cols_count: {info['feature_cols_count']}")
            if info["feature_cols_sample"] is not None:
                print(f"  feature_cols_sample (first 10): {info['feature_cols_sample']}")
        except Exception as exc:
            print(f"  ERROR loading/inspecting model: {exc}", file=sys.stderr)

    print("\nInspection complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

