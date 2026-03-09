# ML Models, Input Data, and Outputs

This document describes the machine learning models used in the JackSparrow Trading Agent project: model types, training scripts, input data, features, and outputs.

---

## Table of Contents

1. [Overview](#overview)
2. [Model Types](#model-types)
3. [Input Data](#input-data)
4. [Features (50 Features)](#features-50-features)
5. [Training Scripts](#training-scripts)
6. [Model Outputs](#model-outputs)
7. [Runtime Inference](#runtime-inference)
8. [File Reference](#file-reference)

---

## Overview

The agent uses a **multi-model ensemble**: several ML models (XGBoost, LightGBM, Random Forest, LSTM, Transformer) are trained on the same feature set and their predictions are combined into a consensus signal. All models consume **50 technical/price/volume features** computed from OHLCV candles and produce a **normalized signal in [-1, 1]** (sell to buy).

| Aspect | Description |
|--------|-------------|
| **Data source** | Delta Exchange API (historical and live candles) |
| **Feature count** | 50 (canonical list in `agent/data/feature_list.py`) |
| **Labeling** | Classification: BUY/SELL/HOLD from forward return thresholds; Regression: future close price |
| **Output** | Normalized prediction in [-1.0, +1.0] and confidence; optional SHAP/feature importance |

---

## Model Types

### 1. XGBoost

- **Role**: Primary predictor for trend and signal classification/regression.
- **Implementation**: `agent/models/xgboost_node.py`
- **Storage**: `agent/model_storage/xgboost/*.pkl`
- **Variants**:
  - **Classifier**: 3-class (SELL=0, HOLD=1, BUY=2) or binary; uses `predict_proba()`.
  - **Regressor**: Predicts absolute future price; runtime converts to return and normalizes to [-1, 1] using current price from context.
- **Input**: Single row of 50 features (same order as `FEATURE_LIST`).
- **Output**: Class probabilities → directional signal, or raw price → return → normalized.

### 2. LightGBM

- **Role**: Alternative gradient boosting; fast inference, good for large feature sets.
- **Implementation**: `agent/models/lightgbm_node.py`
- **Storage**: `agent/model_storage/lightgbm/*.pkl`
- **Input**: Same 50 features as XGBoost.
- **Output**: Normalized to [-1, 1]; supports SHAP for explanations.

### 3. Random Forest

- **Role**: Robust baseline; bagging ensemble, resistant to overfitting.
- **Implementation**: `agent/models/random_forest_node.py`
- **Storage**: `agent/model_storage/random_forest/*.pkl`
- **Input**: Same 50 features.
- **Output**: Normalized to [-1, 1]; built-in feature importance.

### 4. LSTM

- **Role**: Sequence model for temporal dependencies in price/volume.
- **Implementation**: `agent/models/lstm_node.py`
- **Storage**: `agent/model_storage/lstm/*.h5` (Keras/TensorFlow)
- **Input**: Sequence of candles (e.g. 60 steps × 50 features), shape `(batch, sequence_length, 50)`.
- **Output**: Regressor → future price (then normalized like XGBoost regressor); Classifier → class probabilities → normalized signal.
- **Dependency**: TensorFlow/Keras.

### 5. Transformer

- **Role**: Attention-based model for long-range dependencies.
- **Implementation**: `agent/models/transformer_node.py`
- **Storage**: `agent/model_storage/transformer/*.onnx` or `*.pt`/`*.pth`
- **Input**: Sequence format (similar to LSTM); exact shape depends on training.
- **Output**: Normalized to [-1, 1].
- **Dependencies**: ONNX Runtime or PyTorch.

---

## Input Data

### Source

- **API**: Delta Exchange India (`https://api.india.delta.exchange`).
- **Client**: `agent/data/delta_client.py` (REST + optional WebSocket).
- **Candle fields**: `timestamp`, `open`, `high`, `low`, `close`, `volume`.

### Training data

- **Fetch**: Historical candles per symbol and resolution (e.g. 15m, 1h, 4h).
- **Limits**: Delta API returns up to 2,000 candles per request; training scripts use pagination and optional reversal from reverse-chronological to chronological.
- **Typical size**: e.g. ~3,000–5,000 candles per timeframe for training.
- **Train/val/test**: e.g. 70% / 15% / 15% (as in `train_models.py`).

### Runtime data

- **Market data service** and **feature pipeline** build the same 50 features from the latest candles (rolling window).
- **MCP orchestrator** requests features from the feature server and passes a **list of 50 float values** (and optionally `feature_names`) to each model via `MCPModelRequest`.

### Data validation (feature engineering)

- `FeatureEngineering` (in `agent/data/feature_engineering.py`) checks:
  - Required columns: `open`, `high`, `low`, `close`, `volume`.
  - No nulls/invalid numerics; high ≥ low; close within [low, high]; non-negative volume.

---

## Features (50 Features)

Single source of truth: **`agent/data/feature_list.py`** → `FEATURE_LIST` (50 names) and `EXPECTED_FEATURE_COUNT = 50`.

All models that take a single feature vector expect **exactly these 50 features in this order**. Sequence models (LSTM, Transformer) use the same 50 features per time step.

### Feature list (by category)

| Category   | Count | Feature names |
|-----------|-------|----------------|
| **Price** | 16    | `sma_10`, `sma_20`, `sma_50`, `sma_100`, `sma_200`, `ema_12`, `ema_26`, `ema_50`, `close_sma_20_ratio`, `close_sma_50_ratio`, `close_sma_200_ratio`, `high_low_spread`, `close_open_ratio`, `body_size`, `upper_shadow`, `lower_shadow` |
| **Momentum** | 10 | `rsi_14`, `rsi_7`, `stochastic_k_14`, `stochastic_d_14`, `williams_r_14`, `cci_20`, `roc_10`, `roc_20`, `momentum_10`, `momentum_20` |
| **Trend**  | 8     | `macd`, `macd_signal`, `macd_histogram`, `adx_14`, `aroon_up`, `aroon_down`, `aroon_oscillator`, `trend_strength` |
| **Volatility** | 8 | `bb_upper`, `bb_lower`, `bb_width`, `bb_position`, `atr_14`, `atr_20`, `volatility_10`, `volatility_20` |
| **Volume** | 6    | `volume_sma_20`, `volume_ratio`, `obv`, `volume_price_trend`, `accumulation_distribution`, `chaikin_oscillator` |
| **Returns** | 2  | `returns_1h`, `returns_24h` |

### Computation

- **Module**: `agent/data/feature_engineering.py` → `FeatureEngineering`.
- **API**: `compute_feature(feature_name, candles)` returns one float per feature.
- **Convention**: For each candle index, features are computed using a rolling window of candles up to that index (e.g. first 10+ candles may have partial/zero values for long-period indicators).

---

## Training Scripts

### 1. `scripts/train_models.py` (XGBoost classifiers)

- **Purpose**: Train XGBoost **classifiers** for multiple timeframes (e.g. 15m, 1h, 4h).
- **Data**: Fetches historical candles via `DeltaExchangeClient`, computes all 50 features via `FeatureEngineering` and `FEATURE_LIST`.
- **Labels**: Forward return over 1 period; BUY if return > 0.5%, SELL if < -0.5%, else HOLD. Labels mapped to 0/1/2 for XGBoost.
- **Split**: 70% train, 15% validation, 15% test.
- **Model**: `XGBClassifier` (max_depth=6, learning_rate=0.1, n_estimators=100, multi:softprob).
- **Output files**: `agent/model_storage/xgboost/xgboost_classifier_<SYMBOL>_<TIMEFRAME>.pkl` (and optionally under `models/` for 15m).
- **Usage**:
  ```bash
  python scripts/train_models.py --symbol BTCUSD --timeframes 15m 1h 4h
  ```

### 2. `scripts/train_price_prediction_models.py` (XGBoost + optional LSTM)

- **Purpose**: Train both **regression** (future price) and **classification** (BUY/SELL/HOLD) models; supports XGBoost and LSTM.
- **Data**: Delta Exchange with pagination (2,000 candles per request), chronological order; same 50 features.
- **Labels**:
  - Regression: future close price.
  - Classification: same return-based rules (e.g. BUY/SELL/HOLD thresholds).
- **Output files**:
  - XGBoost: `agent/model_storage/xgboost/xgboost_regressor_*.pkl`, `xgboost_classifier_*.pkl`
  - LSTM: `agent/model_storage/lstm/lstm_regressor_*.h5`, `lstm_classifier_*.h5`
- **Usage** (example):
  ```bash
  python scripts/train_price_prediction_models.py --symbol BTCUSD --timeframes 15m 1h 4h --total-candles 5000
  ```
- **Options**: `--regression`, `--no-classification`, `--lstm`, etc. See script help.

### Environment for training

- Delta Exchange credentials: `DELTA_EXCHANGE_API_KEY`, `DELTA_EXCHANGE_API_SECRET` (or project `.env`).
- Python deps: `agent/requirements.txt` (e.g. xgboost, pandas, numpy, tensorflow for LSTM).

---

## Model Outputs

### Standardized prediction (MCP)

All model nodes implement the MCP Model Protocol and return an **`MCPModelPrediction`** (see `agent/models/mcp_model_node.py`):

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | str | Model identifier (e.g. from filename) |
| `model_version` | str | Version string |
| `prediction` | float | **Normalized signal in [-1.0, +1.0]** (sell to buy) |
| `confidence` | float | 0.0–1.0 |
| `reasoning` | str | Short human-readable explanation (e.g. SHAP-based) |
| `features_used` | list[str] | Feature names (e.g. from context) |
| `feature_importance` | dict[str, float] | Per-feature contribution where available |
| `computation_time_ms` | float | Inference time |
| `health_status` | str | e.g. "healthy" |

### Normalization rules

- **Classifier (3-class)**: Probabilities P(SELL), P(HOLD), P(BUY) → directional score `(P(BUY) - P(SELL)) / (P(BUY) + P(SELL))` in [-1, 1], or binary probability mapped to [-1, 1].
- **Classifier (class label)**: 0 → -1, 1 → 0 (HOLD) or mapped to buy/sell, 2 → +1.
- **Regressor**: Raw price → `return_pct = (predicted_price - current_price) / current_price` → `tanh(return_pct / 0.10)` to stay in [-1, 1]. If `current_price` is missing, a fallback normalization is used.

### Consensus

- The **MCP orchestrator** / **model registry** aggregates predictions from all healthy models (weighted by configurable or performance-based weights) into a single consensus signal and forwards it to the reasoning engine and execution layer.

---

## Runtime Inference

1. **Market context** includes latest candles and optional current price.
2. **Feature server** computes the 50 features in `FEATURE_LIST` order and returns a list of (name, value) pairs.
3. **MCP orchestrator** builds `MCPModelRequest`:
   - `features`: `List[float]` of the 50 values in the same order as `FEATURE_LIST`.
   - `context`: includes `feature_names`, `current_price`, and other context.
4. **Model registry** dispatches the request to each loaded model node.
5. Each **model node**:
   - Validates feature count (e.g. 50 for XGBoost/LightGBM/Random Forest).
   - Runs inference (single vector or sequence for LSTM/Transformer).
   - Normalizes output to [-1, 1] and fills `MCPModelPrediction`.
6. Predictions are aggregated into consensus and used for reasoning and trading decisions.

---

## File Reference

| Path | Purpose |
|------|---------|
| `agent/data/feature_list.py` | Canonical 50-feature list and count |
| `agent/data/feature_engineering.py` | Feature computation from OHLCV candles |
| `agent/data/delta_client.py` | Delta Exchange API client for candles |
| `agent/models/mcp_model_node.py` | MCP request/prediction types and base interface |
| `agent/models/xgboost_node.py` | XGBoost classifier/regressor node |
| `agent/models/lightgbm_node.py` | LightGBM node |
| `agent/models/random_forest_node.py` | Random Forest node |
| `agent/models/lstm_node.py` | LSTM (Keras) node |
| `agent/models/transformer_node.py` | Transformer (ONNX/PyTorch) node |
| `agent/models/model_discovery.py` | Discover and register models from storage |
| `agent/models/mcp_model_registry.py` | Registry and prediction aggregation |
| `scripts/train_models.py` | XGBoost classifier training |
| `scripts/train_price_prediction_models.py` | XGBoost + LSTM regression/classification training |
| `agent/model_storage/<type>/*` | Saved model artefacts (.pkl, .h5, .onnx, etc.) |

For more on model storage, discovery, and deployment, see **docs/03-ml-models.md**. For feature engineering and validation, see **docs/04-features.md**.
