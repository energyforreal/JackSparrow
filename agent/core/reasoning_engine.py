"""
MCP Reasoning Engine.

Implements 6-step reasoning chain for trading decisions.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel
import uuid

from agent.data.feature_server import MCPFeatureServer, MCPFeatureResponse
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelResponse
from agent.memory.vector_store import VectorStore


class ReasoningStep(BaseModel):
    """Single step in reasoning chain."""
    step_number: int
    step_name: str
    description: str
    evidence: List[str]
    confidence: float
    timestamp: datetime


class MCPReasoningChain(BaseModel):
    """MCP Reasoning Chain structure."""
    chain_id: str
    timestamp: datetime
    market_context: Dict[str, Any]
    steps: List[ReasoningStep]
    conclusion: str
    final_confidence: float
    model_predictions: List[Dict[str, Any]]
    feature_context: List[Dict[str, Any]]


class MCPReasoningRequest(BaseModel):
    """MCP Reasoning Protocol request."""
    symbol: str
    market_context: Dict[str, Any]
    use_memory: bool = True


class MCPReasoningEngine:
    """MCP Reasoning Engine implementing 6-step reasoning chain."""
    
    def __init__(
        self,
        feature_server: MCPFeatureServer,
        model_registry: MCPModelRegistry,
        vector_store: Optional[VectorStore] = None
    ):
        """Initialize reasoning engine."""
        self.feature_server = feature_server
        self.model_registry = model_registry
        self.vector_store = vector_store
    
    async def initialize(self):
        """Initialize reasoning engine."""
        if self.vector_store:
            await self.vector_store.initialize()
    
    async def shutdown(self):
        """Shutdown reasoning engine."""
        if self.vector_store:
            await self.vector_store.shutdown()
    
    async def generate_reasoning(self, request: MCPReasoningRequest) -> MCPReasoningChain:
        """Generate 6-step reasoning chain."""
        
        chain_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        steps: List[ReasoningStep] = []
        
        # Step 1: Situational Assessment
        step1 = await self._step1_situational_assessment(request)
        steps.append(step1)
        
        # Step 2: Historical Context Retrieval
        step2 = await self._step2_historical_context(request, chain_id)
        steps.append(step2)
        
        # Step 3: Model Consensus Analysis
        step3 = await self._step3_model_consensus(request)
        steps.append(step3)
        
        # Step 4: Risk Assessment
        step4 = await self._step4_risk_assessment(request, steps)
        steps.append(step4)
        
        # Step 5: Decision Synthesis
        step5 = await self._step5_decision_synthesis(request, steps)
        steps.append(step5)
        
        # Step 6: Confidence Calibration
        step6 = await self._step6_confidence_calibration(steps)
        steps.append(step6)
        
        # Extract model predictions and features
        model_predictions = request.market_context.get("model_predictions", [])
        feature_context = request.market_context.get("features", {})
        
        return MCPReasoningChain(
            chain_id=chain_id,
            timestamp=timestamp,
            market_context=request.market_context,
            steps=steps,
            conclusion=step5.description,
            final_confidence=step6.confidence,
            model_predictions=model_predictions,
            feature_context=[{"name": k, "value": v} for k, v in feature_context.items()]
        )
    
    async def _step1_situational_assessment(self, request: MCPReasoningRequest) -> ReasoningStep:
        """Step 1: Assess current market situation."""
        
        context = request.market_context
        features = context.get("features", {})
        
        # Assess market conditions
        evidence = []
        if features.get("rsi_14", 50) > 70:
            evidence.append("RSI indicates overbought conditions")
        elif features.get("rsi_14", 50) < 30:
            evidence.append("RSI indicates oversold conditions")
        
        if features.get("volatility", 0) > 5:
            evidence.append("High volatility detected")
        
        return ReasoningStep(
            step_number=1,
            step_name="Situational Assessment",
            description="Current market conditions analyzed",
            evidence=evidence or ["Market conditions stable"],
            confidence=0.8,
            timestamp=datetime.utcnow()
        )
    
    async def _step2_historical_context(self, request: MCPReasoningRequest, chain_id: str) -> ReasoningStep:
        """Step 2: Retrieve similar historical contexts."""
        
        evidence = []
        
        if self.vector_store:
            try:
                similar_contexts = await self.vector_store.search_similar(
                    context=request.market_context,
                    limit=3
                )
                if similar_contexts:
                    evidence.append(f"Found {len(similar_contexts)} similar historical contexts")
            except Exception as e:
                evidence.append(f"Historical context search unavailable: {e}")
        else:
            evidence.append("Vector store not configured")
        
        return ReasoningStep(
            step_number=2,
            step_name="Historical Context Retrieval",
            description="Similar historical situations retrieved",
            evidence=evidence or ["No similar historical contexts found"],
            confidence=0.7,
            timestamp=datetime.utcnow()
        )
    
    async def _step3_model_consensus(self, request: MCPReasoningRequest) -> ReasoningStep:
        """Step 3: Analyze model consensus."""
        
        model_predictions = request.market_context.get("model_predictions", [])
        
        evidence = []
        if model_predictions:
            consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
            evidence.append(f"Model consensus: {consensus:.2f} ({len(model_predictions)} models)")
            
            if consensus > 0.5:
                evidence.append("Strong bullish consensus")
            elif consensus < -0.5:
                evidence.append("Strong bearish consensus")
            else:
                evidence.append("Mixed signals from models")
        else:
            evidence.append("No model predictions available")
        
        return ReasoningStep(
            step_number=3,
            step_name="Model Consensus Analysis",
            description="Multi-model predictions aggregated",
            evidence=evidence,
            confidence=0.85 if model_predictions else 0.5,
            timestamp=datetime.utcnow()
        )
    
    async def _step4_risk_assessment(self, request: MCPReasoningRequest, previous_steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 4: Assess trading risks."""
        
        evidence = []
        risk_level = "medium"
        
        # Check volatility
        features = request.market_context.get("features", {})
        volatility = features.get("volatility", 0)
        
        if volatility > 5:
            evidence.append("High volatility - increased risk")
            risk_level = "high"
        elif volatility < 2:
            evidence.append("Low volatility - reduced risk")
            risk_level = "low"
        
        # Check position sizing
        portfolio_value = request.market_context.get("portfolio_value", 10000)
        available_balance = request.market_context.get("available_balance", 10000)
        
        if available_balance < portfolio_value * 0.1:
            evidence.append("Limited available balance")
        
        return ReasoningStep(
            step_number=4,
            step_name="Risk Assessment",
            description=f"Risk level: {risk_level}",
            evidence=evidence or ["Risk assessment complete"],
            confidence=0.8,
            timestamp=datetime.utcnow()
        )
    
    async def _step5_decision_synthesis(self, request: MCPReasoningRequest, previous_steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 5: Synthesize final decision."""
        
        model_predictions = request.market_context.get("model_predictions", [])
        
        if not model_predictions:
            conclusion = "HOLD - Insufficient signal strength"
            evidence = ["No model predictions available"]
        else:
            consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
            
            if consensus > 0.7:
                conclusion = "STRONG_BUY - High confidence bullish signal"
            elif consensus > 0.3:
                conclusion = "BUY - Moderate bullish signal"
            elif consensus < -0.7:
                conclusion = "STRONG_SELL - High confidence bearish signal"
            elif consensus < -0.3:
                conclusion = "SELL - Moderate bearish signal"
            else:
                conclusion = "HOLD - Mixed signals, waiting for clearer direction"
            
            evidence = [
                f"Model consensus: {consensus:.2f}",
                f"Based on {len(previous_steps)} analysis steps"
            ]
        
        return ReasoningStep(
            step_number=5,
            step_name="Decision Synthesis",
            description=conclusion,
            evidence=evidence,
            confidence=0.75,
            timestamp=datetime.utcnow()
        )
    
    async def _step6_confidence_calibration(self, steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 6: Calibrate final confidence."""
        
        # Calculate average confidence from all steps
        avg_confidence = sum(step.confidence for step in steps) / len(steps) if steps else 0.5
        
        # Adjust based on step consistency
        confidence_scores = [step.confidence for step in steps]
        consistency = 1.0 - (max(confidence_scores) - min(confidence_scores)) if confidence_scores else 0.0
        
        final_confidence = avg_confidence * consistency
        
        return ReasoningStep(
            step_number=6,
            step_name="Confidence Calibration",
            description=f"Final confidence: {final_confidence:.2f}",
            evidence=[
                f"Average step confidence: {avg_confidence:.2f}",
                f"Consistency score: {consistency:.2f}"
            ],
            confidence=final_confidence,
            timestamp=datetime.utcnow()
        )
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": "up",
            "vector_store_available": self.vector_store is not None
        }

