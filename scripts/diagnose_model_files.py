#!/usr/bin/env python3
"""
Diagnostic script to analyze corrupted model files.

This script examines pickle files to understand why they fail to load.
"""

import sys
import pickle
from pathlib import Path

def analyze_file(file_path: Path):
    """Analyze a model file and report findings."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {file_path}")
    print(f"{'='*60}")
    
    if not file_path.exists():
        print(f"❌ File does not exist")
        return
    
    file_size = file_path.stat().st_size
    print(f"File size: {file_size:,} bytes")
    
    # Read first bytes to check format
    with open(file_path, "rb") as f:
        first_bytes = f.read(32)
    
    print(f"First 32 bytes (hex): {first_bytes.hex()}")
    print(f"First 32 bytes (repr): {repr(first_bytes)}")
    
    # Check if it looks like a pickle file
    if first_bytes.startswith(b'\x80'):
        print("✅ Starts with pickle protocol marker (\\x80)")
        protocol = first_bytes[1] if len(first_bytes) > 1 else None
        print(f"   Pickle protocol version: {protocol}")
    else:
        print(f"❌ Does NOT start with pickle protocol marker")
        print(f"   Expected: Starts with \\x80 (0x80)")
        print(f"   Got: First byte is 0x{first_bytes[0]:02x} ({repr(first_bytes[0:1])})")
    
    # Try to load with pickle
    print("\nAttempting to load with pickle...")
    try:
        with open(file_path, "rb") as f:
            obj = pickle.load(f)
        print(f"✅ Successfully loaded!")
        print(f"   Object type: {type(obj)}")
    except pickle.UnpicklingError as e:
        print(f"❌ UnpicklingError: {e}")
        print(f"   This indicates the file is corrupted or not a valid pickle file")
    except Exception as e:
        print(f"❌ Error loading: {type(e).__name__}: {e}")

if __name__ == "__main__":
    # Files to analyze
    files = [
        Path("agent/model_storage/xgboost/xgboost_BTCUSD_4h_production_20251014_114541.pkl"),
        Path("agent/model_storage/lightgbm/lightgbm_BTCUSD_4h_production_20251014_115655.pkl"),
        Path("agent/model_storage/random_forest/randomforest_BTCUSD_4h_production_20251014_125258.pkl"),
        # Also check working files for comparison
        Path("models/xgboost_BTCUSD_15m.pkl"),
    ]
    
    print("Model File Diagnostic Tool")
    print("="*60)
    
    for file_path in files:
        analyze_file(file_path)

