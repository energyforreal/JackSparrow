# MCP Layer Documentation

## Overview

The Model Context Protocol (MCP) layer is a custom standardized protocol system that enables seamless communication between AI reasoning components, ML models, and data services in **JackSparrow**. This document describes the MCP architecture, protocols, and orchestration mechanisms.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [What is MCP?](#what-is-mcp)
- [MCP Architecture](#mcp-architecture)
- [MCP Feature Protocol](#mcp-feature-protocol)
- [MCP Model Protocol](#mcp-model-protocol)
- [MCP Reasoning Protocol](#mcp-reasoning-protocol)
- [MCP Orchestration](#mcp-orchestration)
- [Integration Points](#integration-points)
- [Model Discovery and Registration](#model-discovery-and-registration)
- [Error Handling and Degradation](#error-handling-and-degradation)
- [Related Documentation](#related-documentation)

---

## What is MCP?

MCP (Model Context Protocol) is a standardized protocol designed for AI systems to:
- Maintain context across components
- Communicate with ML models consistently
- Share features and predictions with versioning
- Enable decision auditing and traceability
- Orchestrate complex reasoning workflows

The Trading Agent implements a custom MCP layer that provides three core protocols:
1. **MCP Feature Protocol** - Standardized feature communication
2. **MCP Model Protocol** - Standardized model prediction interface
3. **MCP Reasoning Protocol** - Structured reasoning chains

---

## MCP Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                    │
│              (FastAPI Backend + Next.js)                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              MCP Orchestration Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ MCP Feature │  │ MCP Model    │  │ MCP Reasoning│  │
│  │ Orchestrator │  │ Orchestrator │  │ Orchestrator │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
└─────────┼─────────────────┼─────────────────┼──────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                    Intelligence Layer                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Feature      │  │ Model        │  │ Reasoning    │  │
│  │ Server        │  │ Registry     │  │ Engine       │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                      Data Layer                          │
│  (Market Data, Models, Vector Store, Database)          │
└─────────────────────────────────────────────────────────┘
```

---

## MCP Feature Protocol

### Purpose

The MCP Feature Protocol standardizes how features are requested, computed, and served across the system with quality monitoring and versioning.

### Protocol Structure

**Feature Request**:
```python
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from enum import Enum

class FeatureQuality(Enum):
    HIGH = "high"        # < 1% missing, fresh data
    MEDIUM = "medium"    # 1-5% missing, slightly stale
    LOW = "low"          # > 5% missing or very stale
    DEGRADED = "degraded"  # Significant quality issues

class MCPFeatureRequest(BaseModel):
    feature_names: List[str]
    symbol: str
    timestamp: Optional[datetime] = None
    version: str = "latest"  # Semantic versioning: "1.2.3" or "latest"
    require_quality: FeatureQuality = FeatureQuality.MEDIUM
```

**Feature Response**:
```python
class MCPFeature(BaseModel):
    name: str
    version: str  # Semantic versioning: "1.2.3"
    value: float
    timestamp: datetime
    quality: FeatureQuality
    metadata: Dict[str, any]
    computation_time_ms: float

class MCPFeatureResponse(BaseModel):
    features: List[MCPFeature]
    quality_score: float  # 0.0 to 1.0
    overall_quality: FeatureQuality
    timestamp: datetime
    request_id: str
```

### Feature Server Implementation

The MCP Feature Server (`agent/data/feature_server.py`) implements the protocol:

```python
class MCPFeatureServer:
    """MCP Feature Server implementing Feature Protocol."""
    
    def __init__(self):
        self.feature_registry = FeatureRegistry()
        self.quality_monitor = FeatureQualityMonitor()
    
    async def get_features(
        self, 
        request: MCPFeatureRequest
    ) -> MCPFeatureResponse:
        """Get features according to MCP Feature Protocol."""
        features = []
        
        for feature_name in request.feature_names:
            # Compute feature
            feature_data = await self._compute_feature(
                feature_name, 
                request.symbol,
                request.timestamp
            )
            
            # Assess quality
            quality = self.quality_monitor.assess_quality(
                feature_data
            )
            
            # Create MCP feature
            mcp_feature = MCPFeature(
                name=feature_name,
                version=self.feature_registry.get_version(feature_name),
                value=feature_data.value,
                timestamp=feature_data.timestamp,
                quality=quality,
                metadata=feature_data.metadata,
                computation_time_ms=feature_data.computation_time_ms
            )
            features.append(mcp_feature)
        
        # Calculate overall quality score
        quality_score = self._calculate_quality_score(features)
        overall_quality = self._determine_overall_quality(quality_score)
        
        return MCPFeatureResponse(
            features=features,
            quality_score=quality_score,
            overall_quality=overall_quality,
            timestamp=datetime.utcnow(),
            request_id=generate_request_id()
        )
```

### Quality Assessment

Features are assessed for quality based on:
- **Data freshness**: How recent is the data?
- **Completeness**: Are there missing values?
- **Validity**: Are values within expected ranges?
- **Consistency**: Is data consistent with historical patterns?

---

## MCP Model Protocol

### Purpose

The MCP Model Protocol standardizes how ML models are registered, invoked, and provide predictions with explanations.

### Protocol Structure

**Model Request**:
```python
class MCPModelRequest(BaseModel):
    request_id: str
    features: List[MCPFeature]
    context: Dict[str, any]
    require_explanation: bool = True
    model_names: Optional[List[str]] = None  # None = all active models
```

**Model Response**:
```python
class MCPModelPrediction(BaseModel):
    model_name: str
    model_version: str
    prediction: float  # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Human-readable explanation (SHAP-based)
    features_used: List[str]
    feature_importance: Dict[str, float]  # SHAP values (feature importance scores)
    computation_time_ms: float
    health_status: str  # "healthy", "degraded", "unhealthy"

class MCPModelResponse(BaseModel):
    request_id: str
    predictions: List[MCPModelPrediction]
    consensus_value: float  # Weighted consensus
    consensus_confidence: float
    agreement_level: float  # 0.0 to 1.0
    timestamp: datetime
```

**Example Request Sequence**:

1. Backend service constructs an `MCPModelRequest` by combining the latest feature snapshot and execution context:
   ```python
   request = MCPModelRequest(
       request_id="req_2025_01_12T10_30_00Z",
       features=current_features,
       context={"portfolio_heat": 0.18, "market_regime": "bull_trending"},
       require_explanation=True
   )
   ```
2. The registry fans out the request to all active models (`xgboost`, `lstm`, `transformer`).
3. Each model node returns an `MCPModelPrediction` with SHAP explanations.
4. The registry aggregates the results, computes consensus, and emits an `MCPModelResponse`.
5. The response is forwarded to the reasoning engine and persisted in the decision memory store.

Use this five-step flow as the canonical reference when adding new model types or debugging inference latency.

**SHAP-Based Explanations**:
All model predictions include SHAP (SHapley Additive exPlanations) based reasoning:
- **Feature Importance**: Each feature's contribution to the prediction (Shapley values)
- **Feature Values**: Actual feature values used in prediction
- **Explanation Generation**: Human-readable explanation of why the model made this prediction
- **Top Contributors**: Identification of top 5-10 features driving the prediction
- **Positive/Negative Contributions**: Both supporting and opposing factors identified
- **Consistency Across Models**: We normalise SHAP outputs across heterogeneous model types so downstream consumers can compare contributions without bespoke conversions.
- **Persisted Metadata**: SHAP vectors and summarised narratives are stored alongside the reasoning chain in the decision memory table (`decision_memory.reasoning_chain`) to support audit replay.

**Example SHAP Explanation**:
```python
# Model generates prediction with SHAP explanation
explanation = {
    "reasoning": "Model predicts BULLISH signal based on strong RSI momentum (RSI_14=65.2 contributes +0.15), positive MACD crossover (MACD_signal=0.5 contributes +0.12), and above-average volume (volume_ratio=1.2 contributes +0.08). The combination of these factors suggests continued upward momentum.",
    "feature_importance": {
        "rsi_14": 0.15,
        "macd_signal": 0.12,
        "volume_ratio": 0.08,
        "price_momentum": 0.06,
        "volatility": -0.03  # Negative contribution
    },
    "top_features": ["rsi_14", "macd_signal", "volume_ratio"]
}
```

**SHAP Implementation**:
- Uses SHAP library (`shap==0.43.0`) for explainability
- Calculates Shapley values for each feature
- Generates human-readable explanations from feature contributions
- Includes both positive and negative contributions
- Normalizes importance scores for consistency
- Model-specific explainers (TreeExplainer for XGBoost/LightGBM, DeepExplainer for LSTM/Transformer)

**SHAP Payload Contract**:

```json
{
  "reasoning": "Model predicts BULLISH signal because ...",
  "feature_importance": {
    "rsi_14": 0.15,
    "macd_signal": 0.12,
    "volume_ratio": 0.08
  },
  "raw_shap_values": [-0.03, 0.12, 0.08, 0.15],
  "baseline_prediction": 0.02,
  "explainer_type": "TreeExplainer",
  "calculated_at": "2025-01-12T10:30:00Z"
}
```

Downstream consumers (frontend, audit tooling, analytics notebooks) rely on the full payload. Do not drop `raw_shap_values` or `baseline_prediction`; they are required to reconstruct plots in observability dashboards.

### Model Registry

The MCP Model Registry (`agent/models/mcp_model_registry.py`) manages all model nodes:

```python
class MCPModelRegistry:
    """Central registry for all ML model nodes."""
    
    def __init__(self):
        self.models: Dict[str, MCPModelNode] = {}
        self.model_metadata: Dict[str, Dict] = {}
        self.performance_tracker = PerformanceTracker()
    
    def register_model(
        self, 
        model: MCPModelNode, 
        metadata: Dict
    ):
        """Register a new model node."""
        self.models[model.model_name] = model
        self.model_metadata[model.model_name] = {
            **metadata,
            "registered_at": datetime.utcnow(),
            "version": model.model_version,
            "model_type": model.model_type
        }
    
    async def get_predictions(
        self, 
        request: MCPModelRequest
    ) -> MCPModelResponse:
        """Get predictions from all active models."""
        # Filter models if specific ones requested
        target_models = (
            [self.models[name] for name in request.model_names]
            if request.model_names
            else list(self.models.values())
        )
        
        # Filter to active models only
        active_models = [
            m for m in target_models 
            if self._is_model_active(m)
        ]
        
        # Run predictions in parallel
        tasks = [
            model.predict(request) 
            for model in active_models
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        predictions = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Model prediction failed: {result}")
                continue
            predictions.append(result)
        
        # Calculate consensus
        consensus_value, consensus_confidence, agreement = \
            self._calculate_consensus(predictions)
        
        return MCPModelResponse(
            request_id=request.request_id,
            predictions=predictions,
            consensus_value=consensus_value,
            consensus_confidence=consensus_confidence,
            agreement_level=agreement,
            timestamp=datetime.utcnow()
        )
    
    def _is_model_active(self, model: MCPModelNode) -> bool:
        """Check if model should be used for predictions."""
        # Check performance threshold
        perf = self.performance_tracker.get_performance(model.model_name)
        if perf and perf.accuracy < 0.5:  # Below random
            return False
        
        # Check health
        if not model.health_monitor.is_healthy():
            return False
        
        return True
```

### Model Node Interface

All model nodes implement the `MCPModelNode` interface:

```python
class MCPModelNode(ABC):
    """Base interface for all MCP model nodes."""
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier."""
        pass
    
    @property
    @abstractmethod
    def model_version(self) -> str:
        """Model version."""
        pass
    
    @property
    @abstractmethod
    def model_type(self) -> str:
        """Model type (xgboost, lstm, transformer, etc.)."""
        pass
    
    @abstractmethod
    async def predict(
        self, 
        request: MCPModelRequest
    ) -> MCPModelPrediction:
        """Generate prediction according to MCP Model Protocol.
        
        Must include SHAP-based explanations in the reasoning field.
        """
        pass
    
    @abstractmethod
    def load_model(self, model_path: str):
        """Load model from file."""
        pass
    
    @abstractmethod
    def get_model_info(self) -> Dict[str, any]:
        """Get model metadata and capabilities."""
        pass
```

---

## MCP Reasoning Protocol

### Purpose

The MCP Reasoning Protocol standardizes how reasoning chains are generated, structured, and stored for decision transparency and learning.

### Protocol Structure

**Reasoning Chain**:
```python
class ReasoningStep(BaseModel):
    step_number: int
    step_name: str
    thought: str
    evidence: List[str]
    confidence: float
    timestamp: datetime

class MCPReasoningChain(BaseModel):
    chain_id: str
    timestamp: datetime
    market_context: Dict[str, any]
    steps: List[ReasoningStep]
    conclusion: str
    final_confidence: float
    decision: Optional[Dict[str, any]] = None
    model_predictions: List[MCPModelPrediction]
    feature_context: List[MCPFeature]
```

### Reasoning Engine

The MCP Reasoning Engine (`agent/core/reasoning_engine.py`) implements the protocol:

```python
class MCPReasoningEngine:
    """MCP Reasoning Engine implementing Reasoning Protocol."""
    
    def __init__(
        self,
        feature_server: MCPFeatureServer,
        model_registry: MCPModelRegistry,
        memory_store: VectorMemoryStore
    ):
        self.feature_server = feature_server
        self.model_registry = model_registry
        self.memory_store = memory_store
    
    async def generate_reasoning_chain(
        self,
        symbol: str,
        context: Dict[str, any]
    ) -> MCPReasoningChain:
        """Generate complete reasoning chain."""
        chain_id = generate_chain_id()
        steps = []
        
        # Step 1: Situational Assessment
        step1 = await self._situational_assessment(symbol, context)
        steps.append(step1)
        
        # Step 2: Historical Context Retrieval
        step2 = await self._historical_context_retrieval(
            symbol, context, step1
        )
        steps.append(step2)
        
        # Step 3: Model Consensus Analysis
        step3 = await self._model_consensus_analysis(
            symbol, context, step1
        )
        steps.append(step3)
        
        # Step 4: Risk Assessment
        step4 = await self._risk_assessment(context, steps)
        steps.append(step4)
        
        # Step 5: Decision Synthesis
        step5 = await self._decision_synthesis(steps)
        steps.append(step5)
        
        # Step 6: Confidence Calibration
        step6 = await self._confidence_calibration(step5, context)
        steps.append(step6)
        
        return MCPReasoningChain(
            chain_id=chain_id,
            timestamp=datetime.utcnow(),
            market_context=context,
            steps=steps,
            conclusion=step6.thought,
            final_confidence=step6.confidence,
            model_predictions=step3.evidence,  # Contains model predictions
            feature_context=step1.evidence  # Contains features
        )
```

---

## MCP Orchestration

### Orchestration Flow

The MCP Orchestration Layer coordinates the interaction between all MCP components:

```
1. Request arrives at MCP Orchestrator
   │
   ├─► MCP Feature Orchestrator
   │   └─► Feature Server (MCP Feature Protocol)
   │       └─► Market Data Service
   │
   ├─► MCP Model Orchestrator
   │   └─► Model Registry (MCP Model Protocol)
   │       ├─► XGBoost Node
   │       ├─► LSTM Node
   │       ├─► Transformer Node
   │       └─► Other Model Nodes
   │
   └─► MCP Reasoning Orchestrator
       └─► Reasoning Engine (MCP Reasoning Protocol)
           ├─► Uses Feature Server
           ├─► Uses Model Registry
           └─► Uses Memory Store
```

### Orchestrator Implementation

```python
class MCPOrchestrator:
    """Main orchestrator for MCP layer."""
    
    def __init__(self):
        self.feature_server = MCPFeatureServer()
        self.model_registry = MCPModelRegistry()
        self.reasoning_engine = MCPReasoningEngine(
            self.feature_server,
            self.model_registry,
            VectorMemoryStore()
        )
    
    async def process_prediction_request(
        self,
        symbol: str,
        context: Dict[str, any]
    ) -> Dict[str, any]:
        """Orchestrate complete prediction workflow."""
        # Generate reasoning chain
        reasoning_chain = await self.reasoning_engine.generate_reasoning_chain(
            symbol, context
        )
        
        # Extract decision
        decision = self._extract_decision(reasoning_chain)
        
        return {
            "reasoning_chain": reasoning_chain,
            "decision": decision,
            "model_predictions": reasoning_chain.model_predictions,
            "features": reasoning_chain.feature_context
        }
```

---

## Integration Points

### Backend Integration

The FastAPI backend integrates with MCP through service layer:

```python
# backend/services/agent_service.py
class AgentService:
    def __init__(self):
        self.mcp_orchestrator = MCPOrchestrator()
    
    async def get_prediction(self, symbol: str):
        """Get prediction via MCP layer."""
        context = await self._build_context(symbol)
        return await self.mcp_orchestrator.process_prediction_request(
            symbol, context
        )
```

### Agent Core Integration

The agent core uses MCP orchestrator for all reasoning:

```python
# agent/core/intelligent_agent.py
class IntelligentAgent:
    def __init__(self):
        self.mcp_orchestrator = MCPOrchestrator()
    
    async def analyze_market(self, symbol: str):
        """Analyze market using MCP layer."""
        context = self._build_market_context(symbol)
        result = await self.mcp_orchestrator.process_prediction_request(
            symbol, context
        )
        return result
```

---

## Model Discovery and Registration

### Automatic Model Discovery

The system automatically discovers models in the model directory:

```python
class ModelDiscovery:
    """Discovers and registers ML models."""
    
    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.registry = MCPModelRegistry()
    
    def discover_models(self):
        """Discover all models in model directory."""
        model_files = self._find_model_files()
        
        for model_file in model_files:
            model_type = self._detect_model_type(model_file)
            model_node = self._create_model_node(model_type, model_file)
            metadata = self._extract_metadata(model_file)
            
            self.registry.register_model(model_node, metadata)
    
    def _detect_model_type(self, model_file: Path) -> str:
        """Detect model type from file."""
        # Check file extension
        if model_file.suffix == '.pkl':
            return self._detect_pickle_model_type(model_file)
        elif model_file.suffix == '.h5' or model_file.suffix == '.keras':
            return 'tensorflow'
        elif model_file.suffix == '.onnx':
            return 'onnx'
        # ... more detection logic
```

---

## Error Handling and Degradation

### Graceful Degradation

The MCP layer implements graceful degradation:

1. **Feature Quality Degradation**: Low quality features are flagged but still used
2. **Model Node Degradation**: Failed models are excluded from consensus
3. **Service Degradation**: System continues with reduced capabilities

### Health Monitoring

Each component reports health status:

```python
class MCPHealthMonitor:
    """Monitor health of MCP components."""
    
    def get_health_status(self) -> Dict[str, any]:
        """Get overall MCP layer health."""
        return {
            "feature_server": self.feature_server.health_status(),
            "model_registry": self.model_registry.health_status(),
            "reasoning_engine": self.reasoning_engine.health_status(),
            "overall_status": self._calculate_overall_status()
        }
```

---

## Related Documentation

- [Architecture Documentation](01-architecture.md) - System architecture overview
- [Logic & Reasoning Documentation](05-logic-reasoning.md) - Reasoning engine details
- [ML Models Documentation](03-ml-models.md) - Model management
- [Backend Documentation](06-backend.md) - Backend integration
- [Build Guide](11-build-guide.md) - Setup instructions

