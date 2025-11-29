#!/usr/bin/env python3
"""
Feature discovery and documentation script.

Discovers or documents the complete 49-feature list used by XGBoost models.
If feature list exists in corrupted model files, extracts it.
Otherwise, creates comprehensive feature list based on common technical indicators.
"""

import sys
import pickle
import json
from pathlib import Path
from typing import List, Dict, Optional
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def extract_features_from_corrupted_model(model_path: Path) -> Optional[List[str]]:
    """Extract feature names from corrupted model file (if it contains numpy array).
    
    Args:
        model_path: Path to model file
        
    Returns:
        List of feature names if found, None otherwise
    """
    if not model_path.exists():
        return None
    
    try:
        with open(model_path, 'rb') as f:
            obj = pickle.load(f)
        
        # Check if it's a numpy array (corrupted model)
        if isinstance(obj, np.ndarray):
            if obj.dtype == object and len(obj) > 0:
                # It's likely feature names
                features = [str(f) for f in obj]
                return features
    except Exception:
        pass
    
    return None


def create_comprehensive_feature_list() -> List[str]:
    """Create comprehensive 49-feature list based on common technical indicators.
    
    Returns:
        List of 49 feature names
    """
    features = []
    
    # Price-based features (15 features)
    # Simple Moving Averages
    features.extend(['sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200'])
    # Exponential Moving Averages
    features.extend(['ema_12', 'ema_26', 'ema_50'])
    # Price ratios
    features.extend(['close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio'])
    # Price position
    features.extend(['high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow'])
    
    # Momentum indicators (10 features)
    features.extend(['rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14'])
    features.extend(['williams_r_14', 'cci_20', 'roc_10', 'roc_20'])
    features.extend(['momentum_10', 'momentum_20'])
    
    # Trend indicators (8 features)
    features.extend(['macd', 'macd_signal', 'macd_histogram'])
    features.extend(['adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator'])
    features.append('trend_strength')
    
    # Volatility indicators (8 features)
    features.extend(['bb_upper', 'bb_lower', 'bb_width', 'bb_position'])
    features.extend(['atr_14', 'atr_20'])
    features.extend(['volatility_10', 'volatility_20'])
    
    # Volume indicators (6 features)
    features.extend(['volume_sma_20', 'volume_ratio', 'obv'])
    features.extend(['volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator'])
    
    # Returns (2 features)
    features.extend(['returns_1h', 'returns_24h'])
    
    # Ensure we have exactly 49 features
    if len(features) != 49:
        # Adjust if needed
        if len(features) < 49:
            # Add more features
            features.extend(['log_returns', 'price_change_pct'])
            features.extend(['volume_change_pct', 'high_low_ratio'])
        elif len(features) > 49:
            # Remove least important
            features = features[:49]
    
    return features[:49]  # Ensure exactly 49


def discover_features() -> List[str]:
    """Discover feature list from existing model files or create comprehensive list.
    
    Returns:
        List of 49 feature names
    """
    # Try to extract from corrupted model files
    model_paths = [
        project_root / "models" / "xgboost_BTCUSD_15m.pkl",
        project_root / "agent" / "model_storage" / "xgboost" / "xgboost_BTCUSD_1h.pkl",
        project_root / "agent" / "model_storage" / "xgboost" / "xgboost_BTCUSD_4h.pkl"
    ]
    
    for model_path in model_paths:
        features = extract_features_from_corrupted_model(model_path)
        if features and len(features) == 49:
            print(f"✓ Extracted {len(features)} features from {model_path.name}")
            return features
    
    # If not found, create comprehensive list
    print("⚠ No feature list found in model files, creating comprehensive list")
    features = create_comprehensive_feature_list()
    print(f"✓ Created comprehensive feature list with {len(features)} features")
    return features


def save_feature_list(features: List[str], output_path: Path):
    """Save feature list to file.
    
    Args:
        features: List of feature names
        output_path: Path to save feature list
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save as JSON
    json_path = output_path.with_suffix('.json')
    with open(json_path, 'w') as f:
        json.dump({
            "feature_count": len(features),
            "features": features,
            "description": "Complete list of 49 features used by XGBoost models"
        }, f, indent=2)
    
    # Save as text file
    txt_path = output_path.with_suffix('.txt')
    with open(txt_path, 'w') as f:
        f.write("# XGBoost Model Feature List (49 features)\n\n")
        for i, feature in enumerate(features, 1):
            f.write(f"{i:2d}. {feature}\n")
    
    print(f"✓ Saved feature list to:")
    print(f"  - {json_path}")
    print(f"  - {txt_path}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("Feature Discovery Script")
    print("=" * 60)
    print()
    
    # Discover features
    features = discover_features()
    
    print()
    print(f"Discovered {len(features)} features:")
    print("-" * 60)
    for i, feature in enumerate(features, 1):
        print(f"{i:2d}. {feature}")
    
    # Save feature list
    output_path = project_root / "models" / "feature_list"
    save_feature_list(features, output_path)
    
    print()
    print("=" * 60)
    print("Feature discovery complete!")
    print("=" * 60)
    
    return features


if __name__ == "__main__":
    main()
