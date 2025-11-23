"""
MCP Reasoning Engine.

Implements 6-step reasoning chain for trading decisions.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
import uuid

from agent.data.feature_server import MCPFeatureServer, MCPFeatureResponse
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelResponse
from agent.memory.vector_store import VectorStore
from agent.events.event_bus import event_bus
from agent.events.schemas import ReasoningRequestEvent, ReasoningCompleteEvent, DecisionReadyEvent, EventType
import structlog

logger = structlog.get_logger()


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
    model_config = ConfigDict(protected_namespaces=())
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
        # Register event handler
        event_bus.subscribe(EventType.REASONING_REQUEST, self._handle_reasoning_request_event)
    
    async def shutdown(self):
        """Shutdown reasoning engine."""
        if self.vector_store:
            await self.vector_store.shutdown()
    
    async def _handle_reasoning_request_event(self, event: ReasoningRequestEvent):
        """Handle reasoning request event.
        
        Args:
            event: Reasoning request event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            market_context = payload.get("market_context", {})
            use_memory = payload.get("use_memory", True)
            
            # Create reasoning request
            request = MCPReasoningRequest(
                symbol=symbol,
                market_context=market_context,
                use_memory=use_memory
            )
            
            # Generate reasoning chain
            reasoning_chain = await self.generate_reasoning(request)
            
            # Emit reasoning complete event
            await self._emit_reasoning_complete_event(event, reasoning_chain)
            
            # Emit decision ready event
            await self._emit_decision_ready_event(event, reasoning_chain)
            
        except Exception as e:
            logger.error(
                "reasoning_request_event_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def _emit_reasoning_complete_event(self, request_event: ReasoningRequestEvent, reasoning_chain: MCPReasoningChain):
        """Emit reasoning complete event.
        
        Args:
            request_event: Original reasoning request event
            reasoning_chain: Generated reasoning chain
        """
        try:
            event = ReasoningCompleteEvent(
                source="reasoning_engine",
                correlation_id=request_event.event_id,
                payload={
                    "symbol": reasoning_chain.market_context.get("symbol", request_event.payload.get("symbol")),
                    "reasoning_chain": {
                        "chain_id": reasoning_chain.chain_id,
                        "steps": [step.dict() for step in reasoning_chain.steps],
                        "conclusion": reasoning_chain.conclusion,
                        "market_context": reasoning_chain.market_context
                    },
                    "final_confidence": reasoning_chain.final_confidence,
                    "timestamp": reasoning_chain.timestamp
                }
            )
            
            await event_bus.publish(event)
            
            logger.info(
                "reasoning_complete_event_emitted",
                symbol=request_event.payload.get("symbol"),
                chain_id=reasoning_chain.chain_id,
                final_confidence=reasoning_chain.final_confidence,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "reasoning_complete_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def _emit_decision_ready_event(self, request_event: ReasoningRequestEvent, reasoning_chain: MCPReasoningChain):
        """Emit decision ready event.
        
        Args:
            request_event: Original reasoning request event
            reasoning_chain: Generated reasoning chain
        """
        try:
            # Extract signal from conclusion
            conclusion = reasoning_chain.conclusion
            if "STRONG_BUY" in conclusion:
                signal = "STRONG_BUY"
                position_size = 0.1  # Max position size
            elif "BUY" in conclusion:
                signal = "BUY"
                position_size = 0.05
            elif "STRONG_SELL" in conclusion:
                signal = "STRONG_SELL"
                position_size = 0.1
            elif "SELL" in conclusion:
                signal = "SELL"
                position_size = 0.05
            else:
                signal = "HOLD"
                position_size = 0.0
            
            event = DecisionReadyEvent(
                source="reasoning_engine",
                correlation_id=request_event.event_id,
                payload={
                    "symbol": reasoning_chain.market_context.get("symbol", request_event.payload.get("symbol")),
                    "signal": signal,
                    "confidence": reasoning_chain.final_confidence,
                    "position_size": position_size,
                    "reasoning_chain": {
                        "chain_id": reasoning_chain.chain_id,
                        "steps": [step.dict() for step in reasoning_chain.steps],
                        "conclusion": reasoning_chain.conclusion
                    },
                    "timestamp": reasoning_chain.timestamp
                }
            )
            
            await event_bus.publish(event)
            
            logger.info(
                "decision_ready_event_emitted",
                symbol=request_event.payload.get("symbol"),
                signal=signal,
                confidence=reasoning_chain.final_confidence,
                position_size=position_size,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "decision_ready_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
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
            # Calculate weighted average by confidence
            total_weight = 0.0
            weighted_sum = 0.0
            
            for p in model_predictions:
                prediction = p.get("prediction", 0.0)
                confidence = p.get("confidence", 0.5)  # Default to 0.5 if missing
                # Ensure confidence is in valid range [0, 1]
                confidence = max(0.0, min(1.0, confidence))
                
                weighted_sum += prediction * confidence
                total_weight += confidence
            
            if total_weight > 0:
                consensus = weighted_sum / total_weight
                avg_confidence = total_weight / len(model_predictions)
            else:
                # Fallback to simple average if all confidences are zero
                consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
                avg_confidence = 0.5
            
            evidence.append(f"Model consensus: {consensus:.2f} ({len(model_predictions)} models, avg confidence: {avg_confidence:.2f})")
            
            if consensus > 0.5:
                evidence.append("Strong bullish consensus")
            elif consensus < -0.5:
                evidence.append("Strong bearish consensus")
            else:
                evidence.append("Mixed signals from models")
        else:
            evidence.append("No model predictions available")
            consensus = 0.0
            avg_confidence = 0.5
        
        return ReasoningStep(
            step_number=3,
            step_name="Model Consensus Analysis",
            description="Multi-model predictions aggregated",
            evidence=evidence,
            confidence=avg_confidence if model_predictions else 0.5,
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
            consensus = 0.0
            avg_confidence = 0.5
        else:
            # Calculate weighted average by confidence
            total_weight = 0.0
            weighted_sum = 0.0
            
            for p in model_predictions:
                prediction = p.get("prediction", 0.0)
                confidence = p.get("confidence", 0.5)  # Default to 0.5 if missing
                # Ensure confidence is in valid range [0, 1]
                confidence = max(0.0, min(1.0, confidence))
                
                weighted_sum += prediction * confidence
                total_weight += confidence
            
            if total_weight > 0:
                consensus = weighted_sum / total_weight
                avg_confidence = total_weight / len(model_predictions)
            else:
                # Fallback to simple average if all confidences are zero
                consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
                avg_confidence = 0.5
            
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
                f"Model consensus: {consensus:.2f} (weighted by confidence, avg: {avg_confidence:.2f})",
                f"Based on {len(previous_steps)} analysis steps",
                f"{len(model_predictions)} model predictions"
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

