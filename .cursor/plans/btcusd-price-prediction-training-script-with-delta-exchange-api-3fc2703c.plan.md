<!-- 3fc2703c-4bdf-4c65-92d9-80d2d0be36bc 3ec8b52e-7683-43bf-9206-9a00c4d0c732 -->
# BTCUSD Price Prediction Training Script - Updated Plan

## Overview

Create a comprehensive ML model training script that predicts BTCUSD prices using historical data from Delta Exchange India. The script will properly handle Delta Exchange API limitations, support both regression (price prediction) and classification (signal prediction) models using XGBoost and LSTM algorithms, and be optimized for Google Colab usage.

## Delta Exchange API Requirements

### API Endpoint Details

- **Endpoint**: `GET /v2/history/candles`
- **Base URL**: `https://api.india.delta.exchange`
- **Authentication**: Required (API key + HMAC-SHA256 signature)
- **Required Parameters**:
  - `symbol` (string): Trading pair symbol (e.g., "BTCUSD")
  - `resolution` (string): Candle interval (must be lowercase)
  - `start` (integer): Start timestamp in Unix seconds (required)
  - `end` (integer): End timestamp in Unix seconds (required)

### API Limitations & Considerations

1. **2,000 Candle Limit**: Maximum candles per request is 2,000

   - For datasets > 2,000 candles, implement pagination
   - Calculate batches: `ceil(total_candles / 2000)`
   - Make multiple requests with adjusted time ranges

2. **Data Ordering**: API returns data in **reverse chronological order** (newest first)

   - Reverse the array to get chronological order for training
   - Important for time-series models (LSTM)

3. **Supported Resolutions**:

   - Valid: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `1d`, `1w`
   - Deprecated (do not use): `7d`, `2w`, `30d`

4. **Response Format**:
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

5. **Rate Limiting**: Add delays between requests (0.5-1 second recommended)

## Implementation Plan

### 1. Create Training Script (`scripts/train_price_prediction_models.py`)

**Key Features:**

- Fetch historical OHLCV data with pagination support (handles > 2,000 candles)
- Reverse data to chronological order (API returns reverse chronological)
- Support both regression (price prediction) and classification (buy/sell/hold) tasks
- Train XGBoost Regressor and LSTM models
- Feature engineering using existing `FeatureEngineering` class
- Model validation and saving
- Google Colab compatibility
- Comprehensive error handling and rate limiting

**Script Structure:**

```python

class PricePredictionTrainer:

def **init**(self, symbol: str = "BTCUSD"):

# Initialize with DeltaExchangeClient

# Set up directories for model storage

async def fetch_historical_data(

self,

interval: str,

total_candles: int = 5000

) -> List[Dict[str, Any]]:

"""

Fetch historical candles with pagination support.

Handles:

        - API limit of 2,000 candles per request
        - Multiple batches for large datasets
        - Data reversal (API returns reverse chronological)
        - Rate limiting between requests

"""

# Calculate number of batches needed

# Fetch each batch sequentially

# Combine and reverse to chronological order

# Return formatted candles list

async def _fetch_candles_batch(

self,

symbol: str,

resolution: str,

start: int,

end: int

) -> List[Dict[str, Any]]:

"""Fetch a single batch of candles (max 2,000)."""

# Use DeltaExchangeClient.get_candles()

# Handle API errors

# Return formatted candles

async def compute_features(

self,

candles: List[Dict[str, Any]]

) -> pd.DataFrame:

"""Compute all 49 features using FeatureEngineering."""

# Reuse existing FeatureEngineering class

# Return DataFrame with features

def create_regres

### To-dos

- [ ] Create scripts/train_price_prediction_models.py with PricePredictionTrainer class, pagination support for >2,000 candles, data reversal, and support for regression/classification with XGBoost and LSTM
- [ ] Implement pagination logic in fetch_historical_data() to handle Delta Exchange API 2,000 candle limit with proper batch fetching and rate limiting
- [ ] Implement data reversal logic to convert API reverse chronological order to chronological order for training
- [ ] Create docs/ml-training-google-colab.md with comprehensive guide including Delta Exchange API limitations, pagination, data ordering, and troubleshooting
- [ ] Update docs/03-ml-models.md to add Price Prediction Models section with API limitations, supported resolutions, and usage examples
- [ ] Update DOCUMENTATION.md to add link to Google Colab training guide in documentation index
- [ ] Create notebooks/train_btcusd_price_prediction.ipynb as optional Colab notebook template with step-by-step cells for training