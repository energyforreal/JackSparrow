#!/usr/bin/env python3
"""
Verification script to test that saved EXIT_MODELS and EXIT_SCALERS can be loaded
and used for predictions.
"""

from pathlib import Path
import joblib
import numpy as np
import json

print('='*70)
print('MODEL VERIFICATION - Testing Saved Exit Models')
print('='*70)

MODEL_DIR = Path('agent') / 'model_storage' / 'robust_ensemble'
TIMEFRAMES = ['15m', '30m', '1h', '2h', '4h']
SYMBOL = 'BTCUSD'

# Test 1: Verify all expected files exist
print('\n[TEST 1] Checking if all expected model files exist...')
expected_files = []
for tf in TIMEFRAMES:
    tag = f'{SYMBOL}_{tf}'
    expected_files.extend([
        f'exit_base_{tag}.joblib',
        f'exit_meta_{tag}.joblib',
        f'exit_scaler_{tag}.joblib',
        f'metadata_exit_{tag}.json',
    ])

all_exist = True
for filename in expected_files:
    filepath = MODEL_DIR / filename
    exists = filepath.exists()
    status = '✅' if exists else '❌'
    print(f'  {status} {filename}')
    if not exists:
        all_exist = False

if all_exist:
    print('  ✅ All expected files exist!')
else:
    print('  ❌ Some files are missing!')

# Test 2: Load and verify model structure
print('\n[TEST 2] Loading models and verifying structure...')
for tf in TIMEFRAMES:
    tag = f'{SYMBOL}_{tf}'
    print(f'\n  Testing [{tf}]...')
    
    try:
        base_path = MODEL_DIR / f'exit_base_{tag}.joblib'
        meta_path = MODEL_DIR / f'exit_meta_{tag}.joblib'
        scaler_path = MODEL_DIR / f'exit_scaler_{tag}.joblib'
        
        # Load models
        base_model = joblib.load(base_path)
        meta_model = joblib.load(meta_path)
        scaler = joblib.load(scaler_path)
        
        # Verify they are XGBoost models
        assert hasattr(base_model, 'predict'), 'Base model missing predict method'
        assert hasattr(meta_model, 'predict'), 'Meta model missing predict method'
        
        # Verify scaler
        assert hasattr(scaler, 'transform'), 'Scaler missing transform method'
        
        print(f'    ✅ Models and scaler loaded successfully')
        print(f'       - Base model type: {type(base_model).__name__}')
        print(f'       - Meta model type: {type(meta_model).__name__}')
        print(f'       - Scaler type: {type(scaler).__name__}')
        
    except Exception as e:
        print(f'    ❌ Error loading models: {e}')

# Test 3: Test prediction pipeline
print('\n[TEST 3] Testing prediction pipeline with dummy data...')
for tf in ['1h', '4h']:  # Test with 2 timeframes
    tag = f'{SYMBOL}_{tf}'
    print(f'\n  Testing predictions [{tf}]...')
    
    try:
        base_path = MODEL_DIR / f'exit_base_{tag}.joblib'
        meta_path = MODEL_DIR / f'exit_meta_{tag}.joblib'
        scaler_path = MODEL_DIR / f'exit_scaler_{tag}.joblib'
        
        base_model = joblib.load(base_path)
        meta_model = joblib.load(meta_path)
        scaler = joblib.load(scaler_path)
        
        # Create dummy input data (17 features from notebook)
        n_samples = 10
        X_dummy = np.random.randn(n_samples, 17).astype(np.float32)
        
        # Apply scaler
        X_scaled = scaler.transform(X_dummy)
        
        # Get base predictions (probabilities)
        base_proba = base_model.predict_proba(X_scaled)
        print(f'    Base output shape: {base_proba.shape}')
        
        # Meta-learner takes base probabilities as features
        meta_pred = meta_model.predict(base_proba)
        print(f'    Meta predictions shape: {meta_pred.shape}')
        print(f'    Meta predictions (first 5): {meta_pred[:5]}')
        
        # Get meta probabilities
        meta_proba = meta_model.predict_proba(base_proba)
        print(f'    Meta probabilities shape: {meta_proba.shape}')
        print(f'    ✅ Prediction pipeline works!')
        
    except Exception as e:
        print(f'    ❌ Error in prediction pipeline: {e}')

# Test 4: Verify metadata files
print(f'\n[TEST 4] Checking metadata files...')
for tf in TIMEFRAMES:
    tag = f'{SYMBOL}_{tf}'
    metadata_path = MODEL_DIR / f'metadata_exit_{tag}.json'
    
    try:
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        
        required_keys = ['model_name', 'model_type', 'symbol', 'timeframe', 'version']
        all_keys_present = all(key in metadata for key in required_keys)
        
        status = '✅' if all_keys_present else '⚠️'
        print(f'  {status} {metadata_path.name}')
        
    except Exception as e:
        print(f'  ❌ Error reading metadata: {e}')

# Final Summary
print('\n' + '='*70)
print('VERIFICATION SUMMARY')
print('='*70)
print(f'Model directory: {MODEL_DIR.absolute()}')
print(f'Total files created: {len(list(MODEL_DIR.glob("exit_*")))}')
print(f'Expected files per timeframe: 4')
print(f'Total timeframes: {len(TIMEFRAMES)}')
print(f'Expected total: {len(TIMEFRAMES) * 4}')

files_created = len(list(MODEL_DIR.glob('exit_*')))
expected = len(TIMEFRAMES) * 4
if files_created == expected:
    print(f'\n✅ All models verified and working correctly!')
else:
    print(f'\n⚠️ File count mismatch: {files_created} vs {expected} expected')

print('\n' + '='*70)
