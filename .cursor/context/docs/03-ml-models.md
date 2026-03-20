# ML Model Management Documentation

## Overview

This document describes how ML models are managed, uploaded, discovered, and integrated into **JackSparrow's** AI reasoning system. The agent intelligently interacts with models to understand their capabilities and reason with them for better trading signals.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Current Production Models (`models/`)](#current-production-models-models)
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

**Current Model Types**:
- **v4 BTCUSD entry/exit ensembles** are stored in `agent/model_storage/jacksparrow_v4_BTCUSD/`
- Each timeframe includes entry/exit models, scalers, features JSON, and metadata JSON
- The system discovers and registers models from v4 metadata files in `MODEL_DIR`

### Currently Integrated Models

As of the latest integration (see [Model Integration Summary](../../MODEL_INTEGRATION_SUMMARY.md)), the system includes **5 v4 BTCUSD models** by timeframe:

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

Model storage is configured via environment variables:

**Root `.env`** (for production models):
```bash
MODEL_DIR=./agent/model_storage/jacksparrow_v4_BTCUSD
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
MIN_CONFIDENCE_THRESHOLD=0.65
```

**Important**:
- `MODEL_DIR` should point to the v4 metadata directory
- v4 discovery reads `metadata_BTCUSD_*.json` directly from `MODEL_DIR` (non-recursive)

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

### Performance Metrics

The system tracks model performance:

```python
class ModelPerformanceTracker:
    """Track model performance over time."""
    
    def record_prediction_outcome(
        self,
        model_name: str,
        prediction: MCPModelPrediction,
        actual_outcome: float
    ):
        """Record prediction and actual outcome."""
        error = abs(prediction.prediction - actual_outcome)
        
        performance_record = {
            "model_name": model_name,
            "prediction": prediction.prediction,
            "actual": actual_outcome,
            "error": error,
            "confidence": prediction.confidence,
            "timestamp": datetime.utcnow()
        }
        
        self.records.append(performance_record)
    
    def calculate_performance_metrics(
        self,
        model_name: str,
        window_size: int = 100
    ) -> Dict:
        """Calculate performance metrics."""
        recent_records = self._get_recent_records(model_name, window_size)
        
        if not recent_records:
            return None
        
        return {
            "accuracy": self._calculate_accuracy(recent_records),
            "mae": self._calculate_mae(recent_records),
            "sharpe_ratio": self._calculate_sharpe(recent_records),
            "win_rate": self._calculate_win_rate(recent_records)
        }
```

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
4. Check model compatibility with Python version
5. Review error logs for specific issues

### Model Prediction Errors

**Problem**: Model predictions fail

**Solutions**:
1. Verify required features are available
2. Check feature format matches model expectations
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

