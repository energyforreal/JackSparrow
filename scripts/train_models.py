#!/usr/bin/env python3
"""
Model training script for XGBoost models.

Fetches historical data, computes features, trains models, and saves them correctly.
"""

import sys
import os
import pickle
import asyncio
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
import structlog

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.data.delta_client import DeltaExchangeClient, DeltaExchangeError
from agent.data.feature_engineering import FeatureEngineering
from agent.core.config import settings

logger = structlog.get_logger()

# Feature list (49 features)
FEATURE_LIST = [
    # Price-based (15 features)
    'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
    'ema_12', 'ema_26', 'ema_50',
    'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
    'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
    # Momentum (10 features)
    'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
    'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
    'momentum_10', 'momentum_20',
    # Trend (8 features)
    'macd', 'macd_signal', 'macd_histogram',
    'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
    'trend_strength',
    # Volatility (8 features)
    'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
    'atr_14', 'atr_20',
    'volatility_10', 'volatility_20',
    # Volume (6 features)
    'volume_sma_20', 'volume_ratio', 'obv',
    'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
    # Returns (2 features)
    'returns_1h', 'returns_24h'
]


class ModelTrainer:
    """Model trainer for XGBoost models."""
    
    def __init__(self, symbol: str = "BTCUSD"):
        """Initialize model trainer."""
        self.symbol = symbol
        self.delta_client = DeltaExchangeClient()
        self.feature_engineering = FeatureEngineering()
        self.models_dir = project_root / "models"
        self.storage_dir = project_root / "agent" / "model_storage" / "xgboost"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    async def fetch_historical_data(
        self,
        interval: str,
        limit: int = 3000
    ) -> List[Dict[str, Any]]:
        """Fetch historical candles from Delta Exchange.
        
        Args:
            interval: Candle interval (15m, 1h, 4h)
            limit: Number of candles to fetch
            
        Returns:
            List of candle dictionaries
        """
        logger.info("fetching_historical_data", symbol=self.symbol, interval=interval, limit=limit)
        
        try:
            # Calculate time range
            start_time, end_time = DeltaExchangeClient._calculate_candle_time_range(interval, limit)
            
            # Fetch candles
            response = await self.delta_client.get_candles(
                symbol=self.symbol,
                resolution=interval,
                start=start_time,
                end=end_time
            )
            
            if "result" not in response or "candles" not in response["result"]:
                raise ValueError(f"Invalid API response: {response}")
            
            candles = response["result"]["candles"]
            
            # Convert to standard format
            formatted_candles = []
            for candle in candles:
                formatted_candles.append({
                    "timestamp": candle.get("time", 0),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": float(candle.get("volume", 0))
                })
            
            logger.info(
                "historical_data_fetched",
                symbol=self.symbol,
                interval=interval,
                candles_count=len(formatted_candles)
            )
            
            return formatted_candles
            
        except Exception as e:
            logger.error(
                "fetch_historical_data_failed",
                symbol=self.symbol,
                interval=interval,
                error=str(e),
                exc_info=True
            )
            raise
    
    async def compute_features(self, candles: List[Dict[str, Any]]) -> pd.DataFrame:
        """Compute all features from candles.
        
        Args:
            candles: List of candle dictionaries
            
        Returns:
            DataFrame with features
        """
        logger.info("computing_features", candles_count=len(candles), feature_count=len(FEATURE_LIST))
        
        feature_data = []
        
        # Compute features for each candle (using rolling window)
        for i in range(len(candles)):
            # Use candles up to current index for feature computation
            window_candles = candles[:i+1]
            
            if len(window_candles) < 10:  # Need minimum candles for some features
                # Fill with zeros for early candles
                feature_row = {feature: 0.0 for feature in FEATURE_LIST}
            else:
                feature_row = {}
                for feature_name in FEATURE_LIST:
                    try:
                        # Compute feature synchronously (feature_engineering is async but we'll handle it)
                        value = await self.feature_engineering.compute_feature(feature_name, window_candles)
                        feature_row[feature_name] = value
                    except Exception as e:
                        logger.warning(
                            "feature_computation_failed",
                            feature=feature_name,
                            candle_index=i,
                            error=str(e)
                        )
                        feature_row[feature_name] = 0.0
            
            feature_data.append(feature_row)
        
        df = pd.DataFrame(feature_data)
        logger.info("features_computed", rows=len(df), columns=len(df.columns))
        
        return df
    
    def create_labels(
        self,
        candles: List[Dict[str, Any]],
        forward_periods: int = 1,
        buy_threshold: float = 0.5,
        sell_threshold: float = -0.5
    ) -> np.ndarray:
        """Create target labels from candles.
        
        Args:
            candles: List of candle dictionaries
            forward_periods: Number of periods to look ahead
            buy_threshold: Return threshold for BUY signal (%)
            sell_threshold: Return threshold for SELL signal (%)
            
        Returns:
            Array of labels: 1 (BUY), -1 (SELL), 0 (HOLD)
        """
        labels = []
        
        for i in range(len(candles)):
            if i + forward_periods >= len(candles):
                # No future data, label as HOLD
                labels.append(0)
                continue
            
            current_close = candles[i]["close"]
            future_close = candles[i + forward_periods]["close"]
            
            # Calculate return percentage
            return_pct = (future_close - current_close) / current_close * 100
            
            if return_pct > buy_threshold:
                labels.append(1)  # BUY
            elif return_pct < sell_threshold:
                labels.append(-1)  # SELL
            else:
                labels.append(0)  # HOLD
        
        return np.array(labels)
    
    def train_model(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        timeframe: str
    ) -> XGBClassifier:
        """Train XGBoost model.
        
        Args:
            X: Feature matrix
            y: Target labels
            timeframe: Timeframe identifier
            
        Returns:
            Trained XGBClassifier model
        """
        logger.info(
            "training_model",
            timeframe=timeframe,
            samples=len(X),
            features=X.shape[1],
            classes=np.unique(y)
        )
        
        # Convert labels to 0, 1, 2 for XGBoost (SELL=-1 -> 0, HOLD=0 -> 1, BUY=1 -> 2)
        y_mapped = y.copy()
        y_mapped[y == -1] = 0  # SELL -> 0
        y_mapped[y == 0] = 1   # HOLD -> 1
        y_mapped[y == 1] = 2   # BUY -> 2
        
        # Train/validation/test split
        train_size = int(len(X) * 0.7)
        val_size = int(len(X) * 0.15)
        
        X_train = X[:train_size]
        y_train = y_mapped[:train_size]
        X_val = X[train_size:train_size+val_size]
        y_val = y_mapped[train_size:train_size+val_size]
        X_test = X[train_size+val_size:]
        y_test = y_mapped[train_size+val_size:]
        
        # Train model
        model = XGBClassifier(
            max_depth=6,
            learning_rate=0.1,
            n_estimators=100,
            objective='multi:softprob',
            num_class=3,
            random_state=42,
            eval_metric='mlogloss'
        )
        
        start_time = time.time()
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )
        training_time = time.time() - start_time
        
        # Evaluate
        train_acc = model.score(X_train, y_train)
        val_acc = model.score(X_val, y_val)
        test_acc = model.score(X_test, y_test)
        
        logger.info(
            "model_trained",
            timeframe=timeframe,
            training_time=training_time,
            train_accuracy=train_acc,
            val_accuracy=val_acc,
            test_accuracy=test_acc
        )
        
        return model, {
            "train_accuracy": train_acc,
            "val_accuracy": val_acc,
            "test_accuracy": test_acc,
            "training_time": training_time
        }
    
    def save_model(
        self,
        model: XGBClassifier,
        timeframe: str,
        metadata: Dict[str, Any]
    ) -> Path:
        """Save trained model to file.
        
        Args:
            model: Trained XGBClassifier instance
            timeframe: Timeframe identifier (15m, 1h, 4h)
            metadata: Training metadata
            
        Returns:
            Path to saved model file
        """
        # Determine save location
        if timeframe == "15m":
            model_path = self.models_dir / f"xgboost_{self.symbol}_{timeframe}.pkl"
        else:
            model_path = self.storage_dir / f"xgboost_{self.symbol}_{timeframe}.pkl"
        
        # CRITICAL: Save the model object, NOT feature names!
        logger.info("saving_model", model_path=str(model_path), model_type=type(model).__name__)
        
        # Verify model is XGBClassifier
        if not isinstance(model, XGBClassifier):
            raise ValueError(f"Model must be XGBClassifier instance, got {type(model)}")
        
        # Backup existing file if it exists
        if model_path.exists():
            backup_path = model_path.with_suffix('.pkl.backup')
            logger.info("backing_up_existing_model", backup_path=str(backup_path))
            model_path.rename(backup_path)
        
        # Save model
        with open(model_path, 'wb') as f:
            pickle.dump(model, f)
        
        logger.info("model_saved", model_path=str(model_path), file_size=model_path.stat().st_size)
        
        # Validate saved model
        self.validate_saved_model(model_path)
        
        return model_path
    
    def validate_saved_model(self, model_path: Path) -> bool:
        """Validate saved model file.
        
        Args:
            model_path: Path to model file
            
        Returns:
            True if valid, raises exception if invalid
        """
        logger.info("validating_saved_model", model_path=str(model_path))
        
        # Load model
        with open(model_path, 'rb') as f:
            loaded_model = pickle.load(f)
        
        # Check type
        if isinstance(loaded_model, np.ndarray):
            raise ValueError(
                f"Model file contains numpy array instead of XGBoost model! "
                f"Array shape: {loaded_model.shape}, dtype: {loaded_model.dtype}. "
                f"This indicates the model was saved incorrectly."
            )
        
        if not isinstance(loaded_model, XGBClassifier):
            raise ValueError(
                f"Model file does not contain XGBClassifier instance. "
                f"Got type: {type(loaded_model)}"
            )
        
        # Check required methods
        if not hasattr(loaded_model, 'predict'):
            raise ValueError("Loaded model does not have 'predict' method")
        
        if not hasattr(loaded_model, 'predict_proba'):
            raise ValueError("Loaded model does not have 'predict_proba' method")
        
        # Test prediction
        dummy_X = np.random.rand(1, len(FEATURE_LIST))
        try:
            prediction = loaded_model.predict(dummy_X)
            proba = loaded_model.predict_proba(dummy_X)
            logger.info(
                "model_validation_success",
                model_path=str(model_path),
                prediction_shape=prediction.shape,
                proba_shape=proba.shape
            )
        except Exception as e:
            raise ValueError(f"Model prediction test failed: {e}")
        
        return True
    
    async def train_timeframe(self, timeframe: str) -> Dict[str, Any]:
        """Train model for a specific timeframe.
        
        Args:
            timeframe: Timeframe (15m, 1h, 4h)
            
        Returns:
            Training results dictionary
        """
        logger.info("starting_training", timeframe=timeframe, symbol=self.symbol)
        
        # Fetch data
        candles = await self.fetch_historical_data(timeframe, limit=3000)
        
        if len(candles) < 500:
            raise ValueError(f"Insufficient data: only {len(candles)} candles")
        
        # Compute features
        X = await self.compute_features(candles)
        
        # Create labels
        y = self.create_labels(candles, forward_periods=1)
        
        # Remove rows with insufficient data (first few rows may have zero features)
        valid_mask = (X.sum(axis=1) != 0) & (y != 0)  # Remove zero-feature rows and HOLD labels for training
        X_clean = X[valid_mask].copy()
        y_clean = y[valid_mask].copy()
        
        if len(X_clean) < 100:
            raise ValueError(f"Insufficient valid samples: {len(X_clean)}")
        
        # Train model
        model, metrics = self.train_model(X_clean, y_clean, timeframe)
        
        # Save model
        model_path = self.save_model(model, timeframe, metrics)
        
        return {
            "timeframe": timeframe,
            "model_path": str(model_path),
            "samples": len(X_clean),
            "features": len(FEATURE_LIST),
            **metrics
        }


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Train XGBoost models for trading agent")
    parser.add_argument("--symbol", default="BTCUSD", help="Trading symbol")
    parser.add_argument("--timeframes", nargs="+", default=["15m", "1h", "4h"], help="Timeframes to train")
    parser.add_argument("--skip-validation", action="store_true", help="Skip model validation")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("XGBoost Model Training Script")
    print("=" * 60)
    print(f"Symbol: {args.symbol}")
    print(f"Timeframes: {', '.join(args.timeframes)}")
    print()
    
    trainer = ModelTrainer(symbol=args.symbol)
    results = []
    
    for timeframe in args.timeframes:
        try:
            print(f"\nTraining model for {timeframe}...")
            result = await trainer.train_timeframe(timeframe)
            results.append(result)
            print(f"✓ Successfully trained {timeframe} model")
            print(f"  Accuracy: Train={result['train_accuracy']:.4f}, Val={result['val_accuracy']:.4f}, Test={result['test_accuracy']:.4f}")
        except Exception as e:
            logger.error("training_failed", timeframe=timeframe, error=str(e), exc_info=True)
            print(f"✗ Failed to train {timeframe} model: {e}")
    
    # Save training summary
    if results:
        summary_path = project_root / "models" / "training_summary.csv"
        summary_df = pd.DataFrame(results)
        summary_df.to_csv(summary_path, index=False)
        print(f"\n✓ Training summary saved to {summary_path}")
    
    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
