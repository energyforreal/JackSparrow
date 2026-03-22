# ML Model Management Documentation

## Overview

This document describes how ML models are managed, uploaded, discovered, and integrated into **JackSparrow's** AI reasoning system. The agent intelligently interacts with models to understand their capabilities and reason with them for better trading signals.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Model Directory Structure](#model-directory-structure)
- [Model Upload Process](#model-upload-process)
- [Model Discovery and Registration](#model-discovery-and-registration)
- [AI Agent Model Intelligence](#ai-agent-model-intelligence)
- [Model Versioning and Management](#model-versioning-and-management)
- [Custom Model Integration](#custom-model-integration)
- [Model Performance Tracking](#model-performance-tracking)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)
- [Related Documentation](#related-documentation)

---

## Model Storage Overview

JackSparrow stores all trained ML models in the **`agent/model_storage/` directory**. Models are automatically discovered and registered on agent startup through the model discovery system.

### Training Authority and Train-Serve Parity

For BTCUSD production-style entry/exit ensembles, the authoritative training path is:

- `notebooks/JackSparrow_Trading_Colab_v4.ipynb`

This notebook uses `UnifiedFeatureEngine`, validates `EXPANDED_FEATURE_LIST` coverage, applies fee-aware TP/SL labeling, and exports timeframe artefacts as a versioned bundle (`entry_*`, `exit_*`, scaler files, `features_*.json`, `metadata_*.json`).

Parity requirements before deployment:

1. `MODEL_DIR` must point to the exact export directory containing `metadata_BTCUSD_*.json`.
2. Metadata `features` and `features_required` must match `feature_store/feature_registry.py` `EXPANDED_FEATURE_LIST` in both order and length.
3. Run feature parity tests (`tests/unit/test_feature_parity.py`) and review pattern-feature importances from the notebook report outputs.

Legacy notebooks such as `notebooks/train_models_colab.ipynb` and `notebooks/train_xgboost_colab.ipynb` are still useful for experiments, but should not be treated as the primary production training authority unless their schema and labels are explicitly aligned with current live metadata.

### Model Storage Location

| Location | Purpose | Environment Variable | Usage |
|----------|---------|---------------------|-------|
| `agent/model_storage/` | All trained ML models | `MODEL_DIR` (points to directory) | Automatic model discovery and registration |

**Current model bundles** (pick one directory for `MODEL_DIR`):

| Directory | Role |
|-----------|------|
| `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19/` | **Full** v5 BTCUSD bundle: five timeframes (15m–4h), entry/exit pairs, standard `entry_model_*` / `exit_model_*` layout. Recommended for local/dev when you want all horizons. |
| `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-21/` | **Default in Docker Compose** (`AGENT_MODEL_DIR` / in-container `MODEL_DIR`): partial experimental layout (e.g. 5m/15m, `entry_long` / `entry_short` naming). Not a complete multi-timeframe set. |

- Discovery reads `metadata_BTCUSD_*.json` from `MODEL_DIR` (non-recursive).
- For production-like behaviour with every documented timeframe, point `MODEL_DIR` at the **2026-03-19** bundle (or your own full export).

### Currently Integrated Models

As of the latest integration (see [Model Integration Summary](model-integration-summary.md)), a **full** v5 deployment includes **5 v5 BTCUSD timeframe nodes**:

- `jacksparrow_BTCUSD_15m`
- `jacksparrow_BTCUSD_30m`
- `jacksparrow_BTCUSD_1h`
- `jacksparrow_BTCUSD_2h`
- `jacksparrow_BTCUSD_4h`

Each model is loaded from `metadata_BTCUSD_<timeframe>.json` and references:
- `entry_model_BTCUSD_<timeframe>.joblib`
- `exit_model_BTCUSD_<timeframe>.joblib`
- `entry_scaler_BTCUSD_<timeframe>.joblib`
- `exit_scaler_BTCUSD_<timeframe>.joblib`
- `features_BTCUSD_<timeframe>.json`

### Environment Configuration

The root `.env` file (documented in [Deployment Documentation](10-deployment.md#environment-variables-reference)) configures model discovery:

```bash
MODEL_DIR=./agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
MIN_CONFIDENCE_THRESHOLD=0.65
```

The `MODEL_DIR` environment variable must point to the directory containing `metadata_BTCUSD_*.json`. In v4-only mode, discovery is metadata-driven and non-recursive.

### ML Models in Docker

When running under Docker, the agent container mounts the host `agent/model_storage/` directory.

- **Bind mount**: `./agent/model_storage:/app/agent/model_storage` (see `docker-compose.yml` agent service).
- **Default in-container `MODEL_DIR`**: override with `AGENT_MODEL_DIR` in root `.env`; otherwise Compose sets  
  `MODEL_DIR=/app/agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-21` (see `docker-compose.yml` / `docker-compose.dev.yml`).

To use the **full** five-timeframe bundle instead, set in root `.env`:

```bash
AGENT_MODEL_DIR=/app/agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19
```

Then restart the agent service.

This means:

- Artefacts you place under `agent/model_storage/` on the host are visible in-container without rebuilding images.
- Updating models: copy files on the host, then `docker compose restart agent`.

**Verification steps before `docker compose up`:**

1. Ensure metadata and joblibs for your chosen bundle exist under the host path that matches `AGENT_MODEL_DIR` / default `MODEL_DIR`.
2. Run:

   ```bash
   python scripts/validate_docker_config.py
   ```

   and confirm it reports at least one model file discovered under `agent/model_storage`.
3. After the stack is running, check the agent logs for a `model_discovery_complete` entry with a `discovered_count > 0`, and confirm the backend health view reports active model nodes.

### XGBoost Dependency Requirements

- Runtime environments must install `xgboost==2.0.2` (see `agent/requirements.txt`) so that `XGBClassifier` and `XGBRegressor` remain available for deserializing the trained models.
- If you rebuild or upgrade the models, ensure `requirements*.txt` stay synchronized with the version used during training.
- When the validator reports `ModuleNotFoundError: No module named 'XGBClassifier'`, re-run `pip install -r agent/requirements.txt` inside the active environment before retrying the load.

### Operational Workflow

1. Train models using the training scripts (see [Model Training](#model-training) section below)
2. Models are automatically saved to `agent/model_storage/xgboost/` during training
3. The model discovery system automatically finds and registers models on agent startup
4. Run the smoke-test commands captured in the [Build Guide](11-build-guide.md#project-commands) before deploying
5. Monitor model performance and update models as needed

---

## Model Training

### Training Script

The project includes a comprehensive model training script (`scripts/train_models.py`) that:
- Fetches historical market data from Delta Exchange API
- Computes all 49 technical indicators/features
- Trains XGBoost classifiers for multiple timeframes
- Saves models correctly (as XGBClassifier instances, not feature names)
- Validates saved models before completion

### Prerequisites

Before training models, ensure:
- Delta Exchange API credentials are configured (`.env` file)
- Sufficient historical data is available (script fetches from API)
- Python dependencies are installed: `pip install -r agent/requirements.txt`

### Training Process

1. **Run the training script**:
   ```bash
   python scripts/train_models.py --symbol BTCUSD --timeframes 15m 1h 4h
   ```

2. **Script will**:
   - Fetch ~3000 candles per timeframe from Delta Exchange
   - Compute 49 features for each candle
   - Create labels based on forward-looking returns
   - Train XGBoost models with train/val/test split (70/15/15)
   - Save models to `agent/model_storage/xgboost/` directory:
     - `agent/model_storage/xgboost/xgboost_BTCUSD_15m.pkl`
     - `agent/model_storage/xgboost/xgboost_BTCUSD_1h.pkl`
     - `agent/model_storage/xgboost/xgboost_BTCUSD_4h.pkl`
   - Validate saved models (ensures they're XGBClassifier instances)

3. **Training metrics** are saved alongside models in the storage directory

### Feature List (49 Features)

The models use 49 technical indicators:

**Price-based (15)**: SMAs (10, 20, 50, 100, 200), EMAs (12, 26, 50), price ratios, candle patterns

**Momentum (10)**: RSI (7, 14), Stochastic (%K, %D), Williams %R, CCI, ROC, Momentum

**Trend (8)**: MACD, MACD signal, MACD histogram, ADX, Aroon (up, down, oscillator), trend strength

**Volatility (8)**: Bollinger Bands (upper, lower, width, position), ATR (14, 20), volatility (10, 20)

**Volume (6)**: Volume SMA, volume ratio, OBV, volume-price trend, accumulation/distribution, Chaikin oscillator

**Returns (2)**: 1h returns, 24h returns

See the feature engineering documentation for the complete list of 49 features.

### Model Validation

**Before deployment**, always validate models:
```bash
python scripts/validate_models_before_deployment.py
```

This checks:
- Model files exist and are readable
- Models are XGBClassifier instances (not numpy arrays)
- Models have required methods (`predict`, `predict_proba`)
- Models can make predictions on sample data

**During startup** (optional):
Set `VALIDATE_MODELS_ON_STARTUP=1` in `.env` to validate models before starting the agent.

### Troubleshooting Training

**Issue**: Models contain numpy arrays instead of trained models
- **Cause**: Model files were saved incorrectly (feature names saved instead of model object)
- **Fix**: Re-run training script: `python scripts/train_models.py`
- **Prevention**: Always use the training script, never manually save feature names

**Issue**: Insufficient data for training
- **Cause**: API returned fewer candles than expected
- **Fix**: Check Delta Exchange API connectivity and increase `limit` parameter

**Issue**: Feature computation fails
- **Cause**: Missing candles or invalid data
- **Fix**: Ensure candles have required fields (open, high, low, close, volume)

---

## Price Prediction Models

### Overview

The project includes a comprehensive price prediction training script (`scripts/train_price_prediction_models.py`) that supports both **regression** (price prediction) and **classification** (buy/sell/hold signal prediction) tasks using XGBoost and LSTM algorithms.

**Key Features**:
- **Pagination Support**: Automatically handles Delta Exchange API 2,000 candle limit
- **Data Reversal**: Converts API reverse chronological order to chronological order
- **Multiple Model Types**: XGBoost Regressor, XGBoost Classifier, LSTM Regressor, LSTM Classifier
- **Google Colab Optimized**: Designed for cloud training environments

### Regressor vs Classifier: Key Differences

**Regressor Models**:
- **Predict**: Absolute future prices (e.g., $50,500)
- **Training**: Uses future close prices as targets
- **Normalization**: Converts absolute price to relative return, then normalizes to [-1, 1]
- **Use Case**: Price prediction with magnitude information

**Classifier Models**:
- **Predict**: Trading signals directly (BUY/SELL/HOLD)
- **Training**: Uses return-based signal labels (BUY if return > 0.5%, SELL if return < -0.5%, HOLD otherwise)
- **Normalization**: Directly normalizes probabilities/class labels to [-1, 1]
- **Use Case**: Direct signal classification without price magnitude

**Consensus Calculation**: Both model types output normalized values in [-1, 1] range, allowing them to be combined in weighted consensus calculations.

## Current Model Support (2025-01-27)

### Supported Model Types

The system now supports **5 different ML model types** through the complete MCP Model Protocol implementation:

#### 1. XGBoost Models ✅ **FULLY IMPLEMENTED**
- **Classifiers**: Predict trading signals directly (buy/sell/hold) with `predict_proba()` method
- **Regressors**: Predict absolute future prices with `predict()` method
- **Auto-detection**: XGBoostNode automatically detects classifier vs regressor types
- **Normalization**: All outputs normalized to [-1, 1] range for consensus

#### 2. LightGBM Models ✅ **FULLY IMPLEMENTED**
- **Complete Implementation**: Full LightGBM Booster support with proper loading
- **SHAP Explanations**: Feature importance extraction for interpretability
- **Same Interface**: Compatible with MCP Model Protocol
- **Performance**: Alternative gradient boosting with potentially better speed

#### 3. Random Forest Models ✅ **FULLY IMPLEMENTED**
- **Scikit-learn Integration**: Full RandomForestClassifier/RandomForestRegressor support
- **Feature Importance**: Built-in feature importance extraction
- **Ensemble Method**: Bagging-based ensemble learning
- **Robust**: Good resistance to overfitting

#### 4. LSTM Models ✅ **FULLY IMPLEMENTED**
- **TensorFlow/Keras Support**: Complete neural network implementation
- **Sequence Processing**: Handles temporal dependencies in price data
- **Configurable Architecture**: Supports various LSTM configurations
- **GPU Acceleration**: Leverages TensorFlow's GPU capabilities

#### 5. Transformer Models ✅ **FULLY IMPLEMENTED**
- **Multi-format Support**: ONNX and PyTorch implementations
- **Attention Mechanisms**: Captures complex relationships in market data
- **Scalable Architecture**: Handles variable input sequences
- **Modern AI**: State-of-the-art transformer architectures

### Implementation Status

All model types are **production-ready** with:
- ✅ Complete MCP Model Node implementations
- ✅ Proper error handling and health monitoring
- ✅ SHAP explanations and feature importance
- ✅ Confidence scoring and normalization
- ✅ Parallel inference support
- ✅ Comprehensive validation

### Delta Exchange API Limitations

The training script properly handles Delta Exchange API constraints:

1. **2,000 Candle Limit**: Maximum candles per request is 2,000
   - Script automatically implements pagination for datasets > 2,000 candles
   - Calculates batches: `ceil(total_candles / 2000)`
   - Makes multiple requests with adjusted time ranges

2. **Reverse Chronological Order**: API returns data in reverse chronological order (newest first)
   - Script automatically reverses data to chronological order (oldest first)
   - Critical for time-series models (LSTM) which require chronological sequences

3. **Supported Resolutions**:
   - Valid: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `1d`, `1w`
   - Deprecated (do not use): `7d`, `2w`, `30d`

4. **Rate Limiting**: Script includes automatic rate limiting (0.75s delay between requests)

### Training Script Usage

#### Basic Usage

```bash
# Train regression and classification models for multiple timeframes
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m 1h 4h \
  --total-candles 5000
```

#### Advanced Options

```bash
# Train only regression models
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m \
  --total-candles 5000 \
  --regression \
  --no-classification

# Train with LSTM models (requires TensorFlow)
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m \
  --total-candles 5000 \
  --lstm

# Train only classification models
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m \
  --total-candles 5000 \
  --classification \
  --no-regression
```

### Model Types

#### 1. XGBoost Regressor

**Purpose**: Predict absolute future price (continuous value)

**Training Target**: Future close price (e.g., if current price is $50,000, predicts $50,500)

**Raw Output**: Absolute price value (e.g., 50500.0)

**Normalization**: The agent automatically converts regressor outputs to relative returns:
1. Calculates return percentage: `(predicted_price - current_price) / current_price`
2. Normalizes return to [-1, 1] range: ±10% return maps to ±1.0
3. Returns beyond ±10% are clamped to ±1.0

**Example**: 
- Current price: $50,000
- Predicted price: $50,500
- Return: +1.0%
- Normalized output: +0.1 (in [-1, 1] range)

**Usage**:
```python
import pickle
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/xgboost/xgboost_regressor_BTCUSD_15m.pkl")
with open(model_path, "rb") as f:
    model = pickle.load(f)

# Predict
features = np.array([[...]])  # 50 features
predicted_price = model.predict(features)  # Absolute price value
```

**Note**: When used in the agent, regressor predictions are automatically normalized to [-1, 1] range using current price from context. If current price is not available, a fallback normalization is used.

#### 2. XGBoost Classifier

**Purpose**: Predict trading signal directly (buy/sell/hold)

**Training Target**: Trading signals based on return thresholds:
- `1` (BUY) if return > 0.5%
- `-1` (SELL) if return < -0.5%
- `0` (HOLD) otherwise

**Raw Output**: Class probabilities or class labels

**Normalization**: Classifier outputs are normalized to [-1, 1] range:
- Probability output [0, 1] → [-1, 1]: `(probability - 0.5) * 2.0`
- Class label (0 or 1) → [-1, 1]: `(label * 2.0) - 1.0`

**Usage**:
```python
import pickle
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/xgboost/xgboost_classifier_BTCUSD_15m.pkl")
with open(model_path, "rb") as f:
    model = pickle.load(f)

# Predict
features = np.array([[...]])  # 50 features
signal = model.predict(features)  # 0, 1, or 2 (or -1, 0, 1 depending on training)
probabilities = model.predict_proba(features)  # [P(SELL), P(HOLD), P(BUY)] or [P(0), P(1)]
```

**Note**: Classifier models directly predict trading signals, so their outputs are more directly interpretable as buy/sell/hold decisions compared to regressors.

#### 3. LSTM Regressor

**Purpose**: Sequence-based price prediction (requires TensorFlow)

**Output**: Future price value

**Usage**:
```python
from tensorflow import keras
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/lstm/lstm_regressor_BTCUSD_15m.h5")
model = keras.models.load_model(model_path)

# Predict (requires sequence of 60 candles)
# Shape: (1, 60, 49) - (batch, sequence_length, features)
sequence = np.array([[[...]]])  # 60 candles × 49 features
predicted_price = model.predict(sequence)
```

#### 4. LSTM Classifier

**Purpose**: Sequence-based signal prediction (requires TensorFlow)

**Output**: Class probabilities

**Usage**:
```python
from tensorflow import keras
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/lstm/lstm_classifier_BTCUSD_15m.h5")
model = keras.models.load_model(model_path)

# Predict (requires sequence of 60 candles)
sequence = np.array([[[...]]])  # 60 candles × 49 features
probabilities = model.predict(sequence)  # [P(SELL), P(HOLD), P(BUY)]
```

### Google Colab Training

For detailed instructions on training models in Google Colab, see:

**[ML Training Guide - Google Colab](ml-training-google-colab.md)**

The guide includes:
- Step-by-step Colab setup instructions
- API limitations and solutions
- Pagination handling details
- Data reversal explanation
- Troubleshooting common issues

**Notebook Template**: A comprehensive Jupyter notebook is available at `notebooks/train_btcusd_price_prediction.ipynb` with:
- Interactive training workflow
- Data exploration and visualization
- Model evaluation and comparison
- Feature importance analysis
- Comprehensive error handling
- Works in both Google Colab and local environments

### Training Output

Models are saved to the `agent/model_storage/` directory, organized by model type:

```
agent/model_storage/
├── xgboost/
│   ├── xgboost_regressor_BTCUSD_15m.pkl
│   ├── xgboost_classifier_BTCUSD_15m.pkl
│   ├── xgboost_regressor_BTCUSD_1h.pkl
│   ├── xgboost_classifier_BTCUSD_1h.pkl
│   └── ...
├── lstm/                              # If TensorFlow available
│   ├── lstm_regressor_BTCUSD_15m.h5
│   ├── lstm_classifier_BTCUSD_15m.h5
│   └── ...
└── price_prediction_training_summary.csv
```

Training metrics are saved to `agent/model_storage/price_prediction_training_summary.csv` with columns:
- `timeframe`: Timeframe identifier
- `model_type`: Model type (xgboost_regressor, xgboost_classifier, etc.)
- `train_metric`: Training metric (RMSE for regression, accuracy for classification)
- `val_metric`: Validation metric
- `test_metric`: Test metric
- `training_time`: Training time in seconds
- `model_path`: Path to saved model file

### Best Practices

1. **Start with Small Datasets**: Test with 3,000 candles before training on larger datasets
2. **Monitor API Usage**: Be aware of API rate limits when fetching large datasets
3. **Validate Models**: Always validate saved models before deployment
4. **Use Appropriate Timeframes**: Match training timeframe to trading strategy
5. **Consider LSTM for Sequences**: LSTM models capture temporal dependencies better than XGBoost

---

## Model Directory Structure

### Directory Layout

```
trading-agent/
├── agent/
│   ├── models/
│   │   ├── __init__.py
│   │   ├── mcp_model_node.py          # Base MCP model interface
│   │   ├── mcp_model_registry.py      # Model registry
│   │   ├── model_discovery.py         # Automatic model discovery
│   │   ├── xgboost_node.py            # XGBoost implementation
│   │   ├── lstm_node.py               # LSTM implementation
│   │   ├── transformer_node.py        # Transformer implementation
│   │   ├── lightgbm_node.py           # LightGBM implementation
│   │   └── random_forest_node.py      # Random Forest implementation
│   │
│   └── model_storage/                  # Uploaded model files
│       ├── xgboost/
│       │   ├── xgboost_v1.0.0.pkl
│       │   ├── xgboost_v1.1.0.pkl
│       │   └── metadata.json
│       ├── lstm/
│       │   ├── lstm_v1.0.0.h5
│       │   └── metadata.json
│       ├── transformer/
│       │   ├── transformer_v1.0.0.onnx
│       │   └── metadata.json
│       └── custom/                     # User-uploaded models
│           ├── my_custom_model.pkl
│           └── metadata.json
```

### Environment Configuration

Model storage is configured via environment variables in the root `.env` file:

```bash
# Points to directory for automatic model discovery
MODEL_DIR=./agent/model_storage
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
MIN_CONFIDENCE_THRESHOLD=0.65
```

**Important**: 
- `MODEL_DIR` is used by the model discovery system to find and register models from `agent/model_storage/` and its subdirectories
- All models are automatically discovered and registered on agent startup
- Models are organized by type in subdirectories (e.g., `xgboost/`, `lstm/`, `transformer/`)

---

## Model Upload Process

### Supported Model Formats

The system supports multiple model formats:

1. **Pickle (.pkl)** - Scikit-learn, XGBoost, LightGBM models
2. **H5/Keras (.h5, .keras)** - TensorFlow/Keras models
3. **ONNX (.onnx)** - ONNX Runtime models
4. **Joblib (.joblib)** - Scikit-learn models
5. **JSON (.json)** - Model weights and architecture

### Upload Directory

Models should be uploaded to the `agent/model_storage/custom/` directory:

```bash
# Create custom models directory if it doesn't exist
mkdir -p agent/model_storage/custom

# Copy your model file
cp my_model.pkl agent/model_storage/custom/

# Create metadata file (optional but recommended)
cat > agent/model_storage/custom/metadata.json << EOF
{
  "model_name": "my_custom_model",
  "model_type": "xgboost",
  "version": "1.0.0",
  "description": "Custom XGBoost model for BTCUSD",
  "features_required": ["rsi_14", "macd_signal", "volume_ratio"],
  "created_at": "2025-01-12T10:00:00Z"
}
EOF
```

### Model Metadata

Each model should have a `metadata.json` file with the following structure:

```json
{
  "model_name": "model_identifier",
  "model_type": "xgboost|lstm|transformer|lightgbm|custom",
  "version": "1.0.0",
  "description": "Model description",
  "author": "Author name",
  "created_at": "2025-01-12T10:00:00Z",
  "features_required": [
    "feature_name_1",
    "feature_name_2"
  ],
  "input_shape": [100, 20],
  "output_type": "regression|classification",
  "target": "price_change|signal",
  "training_data": {
    "period": "2024-01-01 to 2024-12-31",
    "symbol": "BTCUSD"
  },
  "performance_metrics": {
    "accuracy": 0.75,
    "sharpe_ratio": 1.5
  }
}
```

### Quick Upload Example

For repeatable deployments, use the helper script provided under `scripts/`:

```bash
python scripts/install_model.py \
  --source-path ./artefacts/xgboost_BTCUSD_1h.pkl \
  --dest-name xgboost_BTCUSD_1h_prod.pkl \
  --metadata ./artefacts/xgboost_BTCUSD_1h.metadata.json
```

The script performs checksum validation, copies the artefact into `agent/model_storage/custom/`, and updates the registry cache. Review the generated log output in `logs/scripts/install_model.log` to confirm the transfer succeeded.

---

## Model Discovery and Registration

### Automatic Discovery

The system automatically discovers models on startup:

```python
# agent/models/model_discovery.py
class ModelDiscovery:
    """Automatic model discovery and registration."""
    
    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.registry = MCPModelRegistry()
    
    def discover_and_register(self):
        """Discover all models and register them."""
        # Scan model directories
        model_files = self._scan_model_files()
        
        for model_file in model_files:
            try:
                # Detect model type
                model_type = self._detect_model_type(model_file)
                
                # Load metadata
                metadata = self._load_metadata(model_file)
                
                # Create model node
                model_node = self._create_model_node(
                    model_type, 
                    model_file, 
                    metadata
                )
                
                # Register with registry
                self.registry.register_model(model_node, metadata)
                
                logger.info(
                    f"Registered model: {metadata['model_name']} "
                    f"v{metadata['version']} ({model_type})"
                )
            except Exception as e:
                logger.error(f"Failed to register model {model_file}: {e}")
```

### Model Type Detection

The system intelligently detects model types:

```python
def _detect_model_type(self, model_file: Path) -> str:
    """Detect model type from file."""
    # Check file extension
    ext = model_file.suffix.lower()
    
    if ext == '.pkl':
        return self._detect_pickle_model_type(model_file)
    elif ext in ['.h5', '.keras']:
        return 'tensorflow'
    elif ext == '.onnx':
        return 'onnx'
    elif ext == '.joblib':
        return 'scikit-learn'
    else:
        # Try to infer from metadata
        metadata = self._load_metadata(model_file)
        return metadata.get('model_type', 'custom')
```

---

## AI Agent Model Intelligence

### Model Understanding

The AI agent intelligently understands and interacts with ML models:

#### 1. Model Capability Analysis

The agent analyzes each model's capabilities:

```python
class ModelIntelligence:
    """AI agent intelligence for model interaction."""
    
    def analyze_model_capabilities(self, model: MCPModelNode) -> Dict:
        """Analyze what a model can do."""
        model_info = model.get_model_info()
        
        return {
            "model_type": model_info['type'],
            "input_features": model_info['features_required'],
            "output_type": model_info['output_type'],
            "strengths": self._identify_strengths(model_info),
            "limitations": self._identify_limitations(model_info),
            "best_use_cases": self._identify_use_cases(model_info)
        }
    
    def _identify_strengths(self, model_info: Dict) -> List[str]:
        """Identify model strengths."""
        strengths = []
        
        model_type = model_info['type']
        if model_type == 'xgboost':
            strengths.extend([
                "Fast inference",
                "Good for non-linear patterns",
                "Feature importance available"
            ])
        elif model_type == 'lstm':
            strengths.extend([
                "Captures temporal dependencies",
                "Good for sequence patterns",
                "Handles variable-length sequences"
            ])
        elif model_type == 'transformer':
            strengths.extend([
                "Long-range dependencies",
                "Attention mechanisms",
                "Complex pattern recognition"
            ])
        
        return strengths
```

#### 2. Model Reasoning Integration

The agent reasons about which models to use and how to combine them:

```python
def reason_with_models(
    self,
    market_context: Dict,
    available_models: List[MCPModelNode]
) -> Dict:
    """Reason about which models to use and how."""
    
    # Analyze market context
    market_regime = market_context['regime']
    volatility = market_context['volatility']
    
    # Select appropriate models
    selected_models = []
    
    for model in available_models:
        model_capabilities = self.analyze_model_capabilities(model)
        
        # Reason about model suitability
        if self._is_model_suitable(model_capabilities, market_context):
            selected_models.append(model)
    
    # Determine model weights based on context
    model_weights = self._calculate_contextual_weights(
        selected_models,
        market_context
    )
    
    return {
        "selected_models": selected_models,
        "model_weights": model_weights,
        "reasoning": self._generate_reasoning_explanation(
            selected_models,
            market_context
        )
    }
```

#### 3. Model Type Understanding

The agent understands different model types and their characteristics:

**XGBoost Models**:
- Best for: Trend identification, feature-based patterns
- Strengths: Fast, interpretable, handles non-linear relationships
- Use when: Need quick predictions, want feature importance

**LSTM Models**:
- Best for: Sequence patterns, temporal dependencies
- Strengths: Captures time-series patterns, handles sequences
- Use when: Market shows clear temporal patterns

**Transformer Models**:
- Best for: Complex relationships, long-term dependencies
- Strengths: Attention mechanisms, captures complex patterns
- Use when: Need to understand complex market relationships

**LightGBM Models**:
- Best for: Fast gradient boosting, large feature sets
- Strengths: Efficient, good for many features
- Use when: Have many features, need speed

### Model Reasoning Example

```python
# Example: Agent reasoning about models
market_context = {
    "regime": "bull_trending",
    "volatility": "normal",
    "time_horizon": "short_term"
}

reasoning = agent.reason_with_models(market_context, available_models)

# Output:
# {
#   "selected_models": [xgboost_model, lstm_model],
#   "model_weights": {
#     "xgboost": 0.6,
#     "lstm": 0.4
#   },
#   "reasoning": "For bull trending market with normal volatility, 
#                 XGBoost excels at trend identification (60% weight),
#                 while LSTM captures sequence patterns (40% weight)"
# }
```

---

## Model Versioning and Management

### Version Management

Models are versioned using semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes, incompatible with previous versions
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

### Version Tracking

```python
class ModelVersionManager:
    """Manage model versions."""
    
    def register_version(
        self,
        model_name: str,
        version: str,
        model_file: Path,
        metadata: Dict
    ):
        """Register a new model version."""
        version_info = {
            "version": version,
            "file_path": str(model_file),
            "metadata": metadata,
            "registered_at": datetime.utcnow(),
            "is_active": True
        }
        
        self.versions[model_name].append(version_info)
    
    def get_latest_version(self, model_name: str) -> str:
        """Get latest version of a model."""
        versions = self.versions.get(model_name, [])
        if not versions:
            return None
        
        # Sort by version
        sorted_versions = sorted(
            versions,
            key=lambda v: self._parse_version(v['version']),
            reverse=True
        )
        
        return sorted_versions[0]['version']
```

### Model Lifecycle

1. **Upload**: Model file placed in `model_storage/custom/`
2. **Discovery**: System discovers model on next startup
3. **Registration**: Model registered with MCP Model Registry
4. **Validation**: Model validated for compatibility
5. **Activation**: Model activated for use in predictions
6. **Monitoring**: Model performance monitored
7. **Retirement**: Old versions retired when new versions available

---

## Custom Model Integration

### Creating Custom Model Nodes

To integrate a custom model, create a model node class:

```python
# agent/models/custom_model_node.py
from agent.models.mcp_model_node import MCPModelNode
from agent.models.mcp_model_protocol import MCPModelRequest, MCPModelPrediction

class CustomModelNode(MCPModelNode):
    """Custom model node implementation."""
    
    def __init__(self, model_path: str, metadata: Dict):
        self.model_name = metadata['model_name']
        self.model_version = metadata['version']
        self.model_type = metadata['model_type']
        self.model_path = model_path
        self.metadata = metadata
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load model from file."""
        import pickle
        
        with open(self.model_path, 'rb') as f:
            self.model = pickle.load(f)
    
    async def predict(
        self, 
        request: MCPModelRequest
    ) -> MCPModelPrediction:
        """Generate prediction."""
        # Extract features
        features = self._extract_features(request.features)
        
        # Generate prediction
        prediction_value = self.model.predict(features)
        
        # Normalize to -1.0 to +1.0 range
        normalized_prediction = self._normalize_prediction(prediction_value)
        
        # Generate SHAP explanation
        shap_values = self._calculate_shap_values(features)
        reasoning = self._generate_shap_reasoning(shap_values, features)
        feature_importance = self._extract_feature_importance(shap_values, features)
        
        return MCPModelPrediction(
            model_name=self.model_name,
            model_version=self.model_version,
            prediction=normalized_prediction,
            confidence=self._calculate_confidence(features),
            reasoning=reasoning,
            features_used=[f.name for f in request.features],
            feature_importance=feature_importance,
            computation_time_ms=self._measure_computation_time(),
            health_status="healthy"
        )
    
    def _calculate_shap_values(self, features):
        """Calculate SHAP values for explanation."""
        import shap
        explainer = shap.TreeExplainer(self.model)  # For tree-based models
        shap_values = explainer.shap_values(features)
        return shap_values
    
    def _generate_shap_reasoning(self, shap_values, features):
        """Generate human-readable reasoning from SHAP values."""
        # Get top contributing features
        feature_names = [f.name for f in features]
        contributions = dict(zip(feature_names, shap_values))
        top_features = sorted(contributions.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
        
        # Generate explanation
        reasoning_parts = []
        for feature_name, contribution in top_features:
            direction = "supports" if contribution > 0 else "opposes"
            reasoning_parts.append(f"{feature_name} ({contribution:+.3f}) {direction} the prediction")
        
        return f"Model prediction based on: {', '.join(reasoning_parts)}"
    
    def _extract_feature_importance(self, shap_values, features):
        """Extract feature importance from SHAP values."""
        feature_names = [f.name for f in features]
        return dict(zip(feature_names, shap_values))
    
    def get_model_info(self) -> Dict:
        """Get model information."""
        return {
            "type": self.model_type,
            "features_required": self.metadata.get('features_required', []),
            "output_type": self.metadata.get('output_type', 'regression'),
            "capabilities": self.metadata.get('capabilities', [])
        }
```

### Model Requirements

Custom models must:

1. **Implement MCPModelNode interface**
2. **Return predictions in -1.0 to +1.0 range**
3. **Provide reasoning/explanations**
4. **Include metadata.json file**
5. **Support feature extraction from MCPFeature objects**

---

## Model Performance Tracking

### Performance Metrics (implementation: agent/core/learning_system.py)

The `ModelPerformanceTracker` tracks **trade outcomes** (per-model PnL and win/loss), not raw prediction-vs-outcome error. This avoids using a continuous error metric (e.g. MAE) for classifier predictions, which would mix normalized signal [-1, 1] with actual return and mis-rank models.

**Implemented API:**
- `record_trade_outcome(trade_outcome: TradeOutcome, model_predictions: List[Dict])` — records a closed trade for each participating model; triggered from the state machine on `PositionClosedEvent` when `model_predictions` are present in the payload.
- Metrics maintained per model: `total_trades`, `profitable_trades`, `total_pnl`, `win_rate`, `avg_pnl`, `sharpe_ratio` (from recent returns), `recent_performance` (last 50 trades).
- `get_model_weight(model_name, base_weight)` — returns a dynamic weight from win rate, Sharpe, and recent performance (used when learning is enabled).

**If adding prediction-level outcome recording:** For classifiers, use directional accuracy (e.g. `sign(prediction) == sign(actual_return)`) or a classification metric (e.g. AUC), not `abs(prediction - actual_outcome)`, so correct direction is rewarded regardless of magnitude.

---

## Model Inference Testing

### Automated Smoke Test

Use `scripts/test_model_inference.py` to validate that every model stored under `agent/model_storage/` can be discovered, loaded, and queried end-to-end without starting the full agent:

```bash
python scripts/test_model_inference.py \
  --model-dir agent/model_storage
```

The script runs the standard discovery pipeline, issues a lightweight prediction request to each registered node, and prints a confidence summary so regressions are obvious in CI logs. It also reports which artefacts failed to deserialize so you can remove or regenerate them before production deployments.

### Latest Validation Snapshot

Running the script against models in `agent/model_storage/` validates that all models can be discovered, loaded, and queried. The script reports which models load successfully and which fail to deserialize.

Keep this section updated whenever the script uncovers model-health changes so other contributors know which artefacts require attention.

### Feature Vector Expectations

The MCP orchestrator now forwards both the ordered feature values and the associated `feature_names` inside the model request context. Models must continue to:

1. Accept a `List[float]` feature vector shaped exactly like their training data.
2. Read `request.context["feature_names"]` when feature importance needs human-readable labels.
3. Validate the feature count and raise a descriptive error if the input is malformed.

Document the expected feature order inside each model’s metadata so downstream scripts (including the inference smoke test) can source realistic inputs.

---

## Best Practices

### Model Upload

1. **Use semantic versioning** for model versions
2. **Include complete metadata.json** with all required fields
3. **Test model locally** before uploading
4. **Document model capabilities** in metadata
5. **Specify required features** clearly

### Model Development

1. **Follow MCP Model Protocol** for consistency
2. **Normalize predictions** to -1.0 to +1.0 range
3. **Provide meaningful explanations** for predictions
4. **Handle missing features** gracefully
5. **Log model operations** for debugging

### Model Management

1. **Keep old versions** for rollback capability
2. **Monitor model performance** regularly
3. **Retire underperforming models** gracefully
4. **Document model changes** in metadata
5. **Test new versions** before activation

---

## Troubleshooting

### Model Not Discovered

**Problem**: Model not appearing in registry

**Solutions**:
1. Check model file is in correct directory (`model_storage/custom/`)
2. Verify metadata.json exists and is valid JSON
3. Check model file permissions
4. Review agent logs for discovery errors
5. Ensure `MODEL_DISCOVERY_ENABLED=true` in `.env`

### Model Loading Errors

**Problem**: Model fails to load

**Solutions**:
1. Verify model file format is supported
2. Check model dependencies are installed
3. Verify model file is not corrupted
4. Check model compatibility with Python version (re-export pickled models using `Booster.save_model()` or the framework-native exporter before upgrading XGBoost/LightGBM versions)
5. Review error logs for specific issues
6. If you observe `invalid load key` errors, delete the affected file from `agent/model_storage/` and replace it with a freshly serialized artefact from the training environment.

### Model Prediction Errors

**Problem**: Model predictions fail

**Solutions**:
1. Verify required features are available
2. Check feature format matches model expectations (the context now carries both `features` and `feature_names`; custom nodes should rely on those keys instead of positional assumptions)
3. Verify model is properly loaded
4. Check model health status
5. Review prediction logs for errors

### Metadata Mismatch

**Problem**: Registry logs show `metadata_validation_failed` and the model remains inactive.

**Solutions**:
1. Ensure the metadata schema includes all mandatory fields listed in [Model Metadata](#model-metadata) (name, type, version, features, training data block).
2. Confirm the version string matches semantic versioning (`MAJOR.MINOR.PATCH`). Values like `"1.0"` will be rejected.
3. Check that `features_required` lines up with the actual feature names emitted by the MCP Feature Server. Typos cause the registry to reject the model.
4. Run `python scripts/validate_metadata.py --path agent/model_storage/custom/metadata.json` to lint the file locally before restarting the agent.
5. Inspect the agent logs for the detailed validation error payload and adjust the metadata accordingly.

---

## Related Documentation

- [MCP Layer Documentation](02-mcp-layer.md) - MCP protocol details
- [Architecture Documentation](01-architecture.md) - System architecture
- [Logic & Reasoning Documentation](05-logic-reasoning.md) - Reasoning engine
- [Deployment Documentation](10-deployment.md) - Setup instructions
- [Build Guide](11-build-guide.md) - Build instructions

