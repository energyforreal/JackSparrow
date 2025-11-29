# ML Model Training Guide - Google Colab

## Overview

This guide provides comprehensive instructions for training BTCUSD price prediction models using Google Colab. The training script (`scripts/train_price_prediction_models.py`) is optimized for Colab usage and properly handles Delta Exchange API limitations.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Delta Exchange API Setup](#delta-exchange-api-setup)
- [Google Colab Setup](#google-colab-setup)
- [Training Process](#training-process)
- [API Limitations & Considerations](#api-limitations--considerations)
- [Troubleshooting](#troubleshooting)
- [Model Usage](#model-usage)

---

## Prerequisites

Before starting, ensure you have:

1. **Delta Exchange India Account**: Active account with API credentials
2. **Google Colab Account**: Free Google account with Colab access
3. **API Credentials**: API key and secret from Delta Exchange India

---

## Delta Exchange API Setup

### 1. Get API Credentials

1. Log in to [Delta Exchange India](https://india.delta.exchange)
2. Navigate to **Settings** → **API Keys**
3. Create a new API key with read permissions
4. Save your **API Key** and **API Secret** securely

### 2. API Endpoint Details

- **Base URL**: `https://api.india.delta.exchange`
- **Endpoint**: `GET /v2/history/candles`
- **Authentication**: Required (API key + HMAC-SHA256 signature)

### 3. Required Parameters

- `symbol` (string): Trading pair symbol (e.g., "BTCUSD")
- `resolution` (string): Candle interval (must be lowercase)
- `start` (integer): Start timestamp in Unix seconds (required)
- `end` (integer): End timestamp in Unix seconds (required)

---

## API Limitations & Considerations

### 1. 2,000 Candle Limit Per Request

**Important**: The Delta Exchange API limits each request to a maximum of 2,000 candles.

**Solution**: The training script automatically implements pagination:
- Calculates number of batches needed: `ceil(total_candles / 2000)`
- Makes multiple requests with adjusted time ranges
- Combines all batches into a single dataset

**Example**: To fetch 5,000 candles:
- Batch 1: Candles 1-2,000
- Batch 2: Candles 2,001-4,000
- Batch 3: Candles 4,001-5,000

### 2. Reverse Chronological Data Ordering

**Important**: The API returns data in **reverse chronological order** (newest first).

**Solution**: The training script automatically reverses the data:
- Reverses each batch after fetching
- Sorts by timestamp to ensure chronological order
- Removes duplicates based on timestamp

**Impact**: Critical for time-series models (LSTM) which require chronological order.

### 3. Supported Resolutions

**Valid resolutions** (must be lowercase):
- `1m`, `3m`, `5m`, `15m`, `30m`
- `1h`, `2h`, `4h`, `6h`
- `1d`, `1w`

**Deprecated** (do not use):
- `7d`, `2w`, `30d`

### 4. Rate Limiting

**Recommendation**: Add delays between requests (0.5-1 second recommended).

The training script includes automatic rate limiting:
- Default delay: 0.75 seconds between batches
- Prevents API throttling
- Ensures reliable data fetching

### 5. Response Format

```json
{
  "result": {
    "candles": [
      {
        "time": 1712745270,
        "open": 50000.0,
        "high": 50100.0,
        "low": 49900.0,
        "close": 50050.0,
        "volume": 1234.56
      }
    ]
  }
}
```

---

## Google Colab Setup

### Step 1: Open Google Colab

1. Go to [Google Colab](https://colab.research.google.com)
2. Create a new notebook
3. Name it: `BTCUSD_Price_Prediction_Training`

### Step 2: Install Dependencies

Run the following in a Colab cell:

```python
# Install required packages
!pip install xgboost pandas numpy structlog httpx tensorflow scikit-learn

# Verify installation
import xgboost
import pandas as pd
import numpy as np
print("✓ All packages installed successfully")
```

### Step 3: Clone Repository

```python
# Clone the repository
!git clone https://github.com/energyforreal/JackSparrow.git
%cd JackSparrow

# Verify repository structure
!ls -la scripts/
```

### Step 4: Set Up Environment Variables

Create a `.env` file in Colab:

```python
# Set up environment variables
import os

# Delta Exchange API credentials
os.environ["DELTA_EXCHANGE_BASE_URL"] = "https://api.india.delta.exchange"
os.environ["DELTA_EXCHANGE_API_KEY"] = "YOUR_API_KEY_HERE"
os.environ["DELTA_EXCHANGE_API_SECRET"] = "YOUR_API_SECRET_HERE"

print("✓ Environment variables set")
```

**⚠️ Security Note**: Never commit API credentials to version control. Use Colab's secret management or environment variables.

---

## Training Process

### Step 1: Import Training Script

```python
# Add project root to path
import sys
from pathlib import Path
project_root = Path.cwd()
sys.path.insert(0, str(project_root))

# Import training script
from scripts.train_price_prediction_models import PricePredictionTrainer
import asyncio
```

### Step 2: Initialize Trainer

```python
# Initialize trainer
trainer = PricePredictionTrainer(symbol="BTCUSD")
print("✓ Trainer initialized")
```

### Step 3: Train Models

#### Option A: Train All Models (Recommended)

```python
# Train regression and classification models for multiple timeframes
async def train_all():
    results = []
    
    for timeframe in ["15m", "1h", "4h"]:
        print(f"\n{'='*60}")
        print(f"Training {timeframe} models...")
        print(f"{'='*60}")
        
        result = await trainer.train_timeframe(
            timeframe=timeframe,
            total_candles=5000,  # Fetch 5,000 candles
            train_regression=True,
            train_classification=True,
            train_lstm=False  # Set to True if TensorFlow is available
        )
        results.append(result)
        
        print(f"✓ {timeframe} training complete")
    
    return results

# Run training
results = await train_all()
```

#### Option B: Train Specific Timeframe

```python
# Train single timeframe
result = await trainer.train_timeframe(
    timeframe="1h",
    total_candles=5000,
    train_regression=True,
    train_classification=True,
    train_lstm=False
)

print(f"✓ Training complete: {result}")
```

#### Option C: Train Only Regression Models

```python
# Train only regression models
result = await trainer.train_timeframe(
    timeframe="15m",
    total_candles=5000,
    train_regression=True,
    train_classification=False,
    train_lstm=False
)
```

#### Option D: Train Only Classification Models

```python
# Train only classification models
result = await trainer.train_timeframe(
    timeframe="15m",
    total_candles=5000,
    train_regression=False,
    train_classification=True,
    train_lstm=False
)
```

### Step 4: Download Trained Models

```python
# Download models from Colab
from google.colab import files

# List trained models
import os
model_files = [f for f in os.listdir("models/") if f.endswith((".pkl", ".h5"))]
print("Trained models:")
for f in model_files:
    print(f"  - {f}")

# Download specific model
files.download("models/xgboost_regressor_BTCUSD_15m.pkl")
```

---

## Training Script Features

### Pagination Support

The script automatically handles pagination for datasets > 2,000 candles:

```python
# Example: Fetching 5,000 candles
candles = await trainer.fetch_historical_data(
    interval="1h",
    total_candles=5000
)
# Automatically makes 3 API requests (2000 + 2000 + 1000)
```

### Data Reversal

The script automatically reverses API data to chronological order:

```python
# API returns: [newest, ..., oldest]
# Script converts to: [oldest, ..., newest]
# Critical for LSTM training
```

### Feature Engineering

The script computes all 49 features using the existing `FeatureEngineering` class:

- **Price-based (15)**: SMAs, EMAs, price ratios, candle patterns
- **Momentum (10)**: RSI, Stochastic, Williams %R, CCI, ROC, Momentum
- **Trend (8)**: MACD, ADX, Aroon, trend strength
- **Volatility (8)**: Bollinger Bands, ATR, volatility
- **Volume (6)**: Volume SMA, OBV, accumulation/distribution
- **Returns (2)**: 1h returns, 24h returns

### Model Types

The script supports multiple model types:

1. **XGBoost Regressor**: Price prediction (continuous values)
2. **XGBoost Classifier**: Signal prediction (buy/sell/hold)
3. **LSTM Regressor**: Sequence-based price prediction (requires TensorFlow)
4. **LSTM Classifier**: Sequence-based signal prediction (requires TensorFlow)

---

## Troubleshooting

### Issue: API Authentication Error

**Error**: `Delta Exchange authentication error 401/403`

**Solutions**:
1. Verify API credentials are correct
2. Check API key has read permissions
3. Ensure system clock is synchronized (Colab handles this automatically)
4. Verify base URL is `https://api.india.delta.exchange`

### Issue: Insufficient Data

**Error**: `Insufficient data: only X candles`

**Solutions**:
1. Reduce `total_candles` parameter
2. Check API connectivity
3. Verify symbol is correct (e.g., "BTCUSD")
4. Try different timeframe

### Issue: Pagination Fails

**Error**: `batch_fetch_failed` or timeout errors

**Solutions**:
1. Increase `RATE_LIMIT_DELAY` in script (default: 0.75s)
2. Reduce `total_candles` to fetch fewer batches
3. Check network connectivity in Colab
4. Verify API rate limits haven't been exceeded

### Issue: Data Ordering Issues

**Error**: LSTM model performance is poor

**Solutions**:
1. Verify data reversal is working (check timestamps are ascending)
2. Ensure chronological order: `candles[0]["timestamp"] < candles[-1]["timestamp"]`
3. Check for duplicate timestamps (script removes them automatically)

### Issue: Feature Computation Fails

**Error**: `feature_computation_failed`

**Solutions**:
1. Ensure candles have required fields: `open`, `high`, `low`, `close`, `volume`
2. Check for invalid data (NaN, Inf, negative prices)
3. Verify minimum candles available (need at least 10 for some features)

### Issue: TensorFlow/LSTM Not Available

**Error**: `TensorFlow not available, skipping LSTM training`

**Solutions**:
1. Install TensorFlow: `!pip install tensorflow`
2. Set `train_lstm=False` if TensorFlow is not needed
3. LSTM training is optional; XGBoost models work without TensorFlow

### Issue: Memory Errors in Colab

**Error**: `Out of memory` or `RAM limit exceeded`

**Solutions**:
1. Reduce `total_candles` parameter (e.g., 3000 instead of 5000)
2. Train one timeframe at a time
3. Use Colab Pro for more RAM (optional)
4. Clear variables: `del candles, X, y` after training

---

## Model Usage

### Loading Trained Models

#### XGBoost Models

```python
import pickle

# Load regressor
with open("models/xgboost_regressor_BTCUSD_15m.pkl", "rb") as f:
    regressor = pickle.load(f)

# Load classifier
with open("models/xgboost_classifier_BTCUSD_15m.pkl", "rb") as f:
    classifier = pickle.load(f)
```

#### LSTM Models

```python
from tensorflow import keras

# Load LSTM model
lstm_model = keras.models.load_model("models/lstm_regressor_BTCUSD_15m.h5")
```

### Making Predictions

#### Regression (Price Prediction)

```python
# Prepare features (49 features)
features = np.array([[...]])  # Shape: (1, 49)

# Predict future price
predicted_price = regressor.predict(features)
print(f"Predicted price: ${predicted_price[0]:.2f}")
```

#### Classification (Signal Prediction)

```python
# Prepare features
features = np.array([[...]])  # Shape: (1, 49)

# Predict signal
prediction = classifier.predict(features)
probabilities = classifier.predict_proba(features)

# Map prediction: 0=SELL, 1=HOLD, 2=BUY
signal_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
signal = signal_map[prediction[0]]
confidence = probabilities[0].max()

print(f"Signal: {signal} (confidence: {confidence:.2%})")
```

---

## Best Practices

1. **Start Small**: Begin with 3,000 candles to test the setup
2. **Monitor API Usage**: Check API rate limits and quotas
3. **Save Progress**: Download models after each successful training
4. **Version Control**: Use descriptive filenames with timestamps
5. **Validate Models**: Test predictions before deploying
6. **Document Parameters**: Record training parameters for reproducibility

---

## Notebook Template

A comprehensive Jupyter notebook template is available at `notebooks/train_btcusd_price_prediction.ipynb` with:

- Step-by-step training instructions
- Data exploration and visualization
- Model evaluation and comparison
- Feature importance analysis
- Comprehensive error handling
- Progress tracking

The notebook is optimized for both Google Colab and local execution.

## Related Documentation

- [ML Models Documentation](03-ml-models.md) - Model management and usage
- [Feature Engineering](04-features.md) - Feature computation details
- [Deployment Documentation](10-deployment.md) - Production deployment guide
- [Notebook Improvements](notebook-improvements.md) - Detailed list of notebook enhancements

---

## Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [API Limitations](#api-limitations--considerations)
3. Consult [ML Models Documentation](03-ml-models.md)
4. Open an issue on GitHub

---

**Last Updated**: 2025-01-27
