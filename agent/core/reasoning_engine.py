"""
MCP Reasoning Engine.

Implements 6-step reasoning chain for trading decisions.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
import statistics
import uuid

from agent.data.feature_server import MCPFeatureServer, MCPFeatureResponse
from agent.models.mcp_model_registry import (
    MCPModelRegistry,
    MCPModelResponse,
    NoHealthyModelPredictionsError,
)
from agent.memory.vector_store import VectorMemoryStore
from agent.events.event_bus import event_bus
from agent.events.schemas import ReasoningRequestEvent, ReasoningCompleteEvent, DecisionReadyEvent, EventType
from agent.core.config import settings
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
    # Optional metadata fields
    data_freshness_seconds: Optional[int] = None
    similarity_score: Optional[float] = None
    feature_quality_score: Optional[float] = None


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
        vector_store: Optional[VectorMemoryStore] = None
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
            
        except NoHealthyModelPredictionsError:
            # Race: reasoning requested before model_predictions in context; skip gracefully
            logger.debug(
                "reasoning_request_skipped_no_predictions",
                event_id=event.event_id,
                symbol=payload.get("symbol"),
                message="Skipping reasoning - no model_predictions in market_context (decision may already be emitted).",
            )
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
                        "steps": [step.model_dump() for step in reasoning_chain.steps],
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
            # Defensive check: ensure model_predictions are present before
            # emitting any trading decision.
            prediction_count = len(reasoning_chain.model_predictions or [])
            if prediction_count == 0:
                logger.error(
                    "decision_ready_event_skipped_no_model_predictions",
                    symbol=reasoning_chain.market_context.get(
                        "symbol", request_event.payload.get("symbol")
                    ),
                    message="Skipping DecisionReadyEvent because reasoning_chain.model_predictions is empty.",
                )
                return

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
                        "steps": [step.model_dump() for step in reasoning_chain.steps],
                        "conclusion": reasoning_chain.conclusion,
                        "market_context": reasoning_chain.market_context,
                        "model_predictions": reasoning_chain.model_predictions
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
                event_id=event.event_id,
                timestamp=reasoning_chain.timestamp,
                message="Decision ready event published - will trigger signal_update broadcast to frontend"
            )
            
        except Exception as e:
            logger.error(
                "decision_ready_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def generate_reasoning(self, request: MCPReasoningRequest) -> MCPReasoningChain:
        """Generate 6-step reasoning chain."""
        # Accept both "model_predictions" and "predictions" (model_handler sends "predictions")
        model_predictions = request.market_context.get("model_predictions") or request.market_context.get("predictions") or []

        # Enforce that reasoning is only generated when real model predictions
        # are present. This prevents pseudo-decisions based solely on features
        # or other fallbacks.
        if not model_predictions:
            logger.error(
                "reasoning_generate_no_model_predictions",
                message="generate_reasoning called without model_predictions in market_context.",
            )
            raise NoHealthyModelPredictionsError(
                "Cannot generate reasoning without model_predictions in market_context."
            )

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
        
        # Extract model predictions and features
        feature_context = request.market_context.get("features", {})

        # Step 6: Confidence Calibration
        step6 = await self._step6_confidence_calibration(steps, model_predictions)
        steps.append(step6)
        
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

        # Use feature quality score as confidence when available; otherwise fall
        # back to the qualitative feature_quality label, and finally to 0.0.
        raw_quality = context.get("quality_score")
        if isinstance(raw_quality, (int, float)):
            quality_score = max(0.0, min(1.0, float(raw_quality)))
        else:
            # Older callers may only provide a qualitative feature_quality
            # string such as "high", "medium", "low", or "degraded".
            feature_quality = context.get("feature_quality")
            if isinstance(feature_quality, str):
                quality_mapping = {
                    "high": 1.0,
                    "medium": 0.7,
                    "low": 0.4,
                    "degraded": 0.1,
                }
                quality_score = quality_mapping.get(feature_quality.lower(), 0.0)
            else:
                quality_score = 0.0

        confidence = quality_score

        # Include quality score in evidence if available
        if quality_score > 0:
            evidence.append(f"Data quality: {quality_score:.2f}")
        else:
            evidence.append("Data quality score unavailable")

        # Calculate data freshness from market data timestamps
        data_freshness_seconds = None
        market_timestamp = request.market_context.get("timestamp")
        if market_timestamp:
            try:
                if isinstance(market_timestamp, str):
                    market_time = datetime.fromisoformat(market_timestamp.replace('Z', '+00:00'))
                else:
                    market_time = market_timestamp
                data_freshness_seconds = int((datetime.utcnow() - market_time).total_seconds())
            except (ValueError, TypeError):
                pass

        return ReasoningStep(
            step_number=1,
            step_name="Situational Assessment",
            description="Current market conditions analyzed",
            evidence=evidence or ["Market conditions stable"],
            confidence=confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds,
            feature_quality_score=quality_score if quality_score > 0 else None
        )
    
    async def _step2_historical_context(self, request: MCPReasoningRequest, chain_id: str) -> ReasoningStep:
        """Step 2: Retrieve similar historical contexts."""

        from agent.memory.vector_store import DecisionContext

        evidence = []
        confidence = 0.0
        similar_contexts = None  # Initialize to avoid UnboundLocalError
        avg_similarity = 0.0

        if self.vector_store:
            try:
                # Create DecisionContext from market context for similarity search
                query_context = DecisionContext(
                    context_id=f"query-{chain_id}",
                    symbol=request.symbol,
                    timestamp=datetime.utcnow(),
                    features=request.market_context.get("features", {}),
                    market_context=request.market_context,
                    decision={}  # Empty decision for query context
                )

                similar_contexts = await self.vector_store.find_similar_contexts(
                    query_context=query_context,
                    limit=3
                )

                if similar_contexts:
                    # Extract similarity scores
                    similarity_scores = [score for _, score in similar_contexts]
                    avg_similarity = sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0.0

                    # Use average similarity as confidence, clamped to [0, 1]
                    confidence = max(0.0, min(1.0, avg_similarity))

                    evidence.append(f"Found {len(similar_contexts)} similar historical contexts")
                    evidence.append(f"Average similarity: {avg_similarity:.2f}")
                else:
                    evidence.append("No similar historical contexts found")
                    avg_similarity = 0.0

            except Exception as e:
                evidence.append(f"Historical context search unavailable: {e}")
        else:
            evidence.append("Vector store not configured")

        return ReasoningStep(
            step_number=2,
            step_name="Historical Context Retrieval",
            description="Similar historical situations retrieved",
            evidence=evidence,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            similarity_score=avg_similarity if similar_contexts else None
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
                confidence = p.get("confidence", 0.0)  # Treat missing confidence as 0.0
                # Ensure confidence is in valid range [0, 1]
                confidence = max(0.0, min(1.0, confidence))
                
                weighted_sum += prediction * confidence
                total_weight += confidence
            
            if total_weight > 0:
                consensus = weighted_sum / total_weight
                avg_confidence = total_weight / len(model_predictions)
            else:
                # All confidences are zero – use simple average and reflect uncertainty in avg_confidence
                consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
                avg_confidence = 0.0
            
            # Model disagreement filter: dampen consensus when predictions disagree strongly
            predictions_vals = [p.get("prediction", 0) for p in model_predictions]
            thresh = getattr(settings, "model_disagreement_threshold", 0.6)
            if len(predictions_vals) > 1:
                pred_stdev = statistics.stdev(predictions_vals)
                if pred_stdev > thresh:
                    # Scalping: reduce excessive consensus suppression when models disagree.
                    # Keep at least 50% of the consensus rather than allowing near-zero collapse.
                    damping_factor = max(0.5, 1.0 - 0.5 * (pred_stdev - thresh))
                    consensus_before = consensus
                    evidence.append(
                        f"High model disagreement (stdev={pred_stdev:.2f}) — signal suppressed"
                    )
                    consensus *= damping_factor
                    if getattr(settings, "diagnostics_enabled", True):
                        logger.info(
                            "model_consensus_dampened",
                            symbol=request.symbol,
                            pred_stdev=float(pred_stdev),
                            threshold=float(thresh),
                            damping_factor=float(damping_factor),
                            consensus_before=float(consensus_before),
                            consensus_after=float(consensus),
                            models=len(predictions_vals),
                        )

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
            avg_confidence = 0.0

        # Calculate data freshness from market data timestamps
        data_freshness_seconds = None
        market_timestamp = request.market_context.get("timestamp")
        if market_timestamp:
            try:
                if isinstance(market_timestamp, str):
                    market_time = datetime.fromisoformat(market_timestamp.replace('Z', '+00:00'))
                else:
                    market_time = market_timestamp
                data_freshness_seconds = int((datetime.utcnow() - market_time).total_seconds())
            except (ValueError, TypeError):
                pass

        return ReasoningStep(
            step_number=3,
            step_name="Model Consensus Analysis",
            description="Multi-model predictions aggregated",
            evidence=evidence,
            confidence=avg_confidence if model_predictions else 0.0,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds
        )
    
    async def _step4_risk_assessment(self, request: MCPReasoningRequest, previous_steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 4: Assess trading risks."""

        evidence = []
        risk_level = "medium"
        confidence = 0.0

        # Check volatility data availability (+0.2 if available)
        features = request.market_context.get("features", {})
        volatility = features.get("volatility", None)

        if volatility is not None:
            confidence += 0.2
            if volatility > 5:
                evidence.append("High volatility - increased risk")
                risk_level = "high"
            elif volatility < 2:
                evidence.append("Low volatility - reduced risk")
                risk_level = "low"
        else:
            evidence.append("Volatility data unavailable")

        # Check portfolio data availability (+0.2 if available)
        portfolio_value = request.market_context.get("portfolio_value", None)
        available_balance = request.market_context.get("available_balance", None)

        if portfolio_value is not None and available_balance is not None:
            confidence += 0.2
            if available_balance < portfolio_value * 0.1:
                evidence.append("Limited available balance")
        else:
            evidence.append("Portfolio data unavailable")

        # Check risk metrics calculation (+0.2 if metrics can be calculated)
        # This could include drawdown, Sharpe ratio, etc.
        has_risk_metrics = (
            request.market_context.get("max_drawdown_current") is not None or
            request.market_context.get("sharpe_ratio_rolling") is not None or
            request.market_context.get("portfolio_heat") is not None
        )

        if has_risk_metrics:
            confidence += 0.2
            evidence.append("Risk metrics available")
        else:
            evidence.append("Risk metrics unavailable")

        # Ensure confidence doesn't exceed 1.0
        confidence = min(1.0, confidence)

        # Calculate data freshness from market data timestamps
        data_freshness_seconds = None
        market_timestamp = request.market_context.get("timestamp")
        if market_timestamp:
            try:
                if isinstance(market_timestamp, str):
                    market_time = datetime.fromisoformat(market_timestamp.replace('Z', '+00:00'))
                else:
                    market_time = market_timestamp
                data_freshness_seconds = int((datetime.utcnow() - market_time).total_seconds())
            except (ValueError, TypeError):
                pass

        return ReasoningStep(
            step_number=4,
            step_name="Risk Assessment",
            description=f"Risk level: {risk_level}",
            evidence=evidence,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds
        )
    
    async def _step5_decision_synthesis(self, request: MCPReasoningRequest, previous_steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 5: Synthesize final decision."""
        
        model_predictions = request.market_context.get("model_predictions", [])
        
        if not model_predictions:
            conclusion = "HOLD - Insufficient signal strength"
            evidence = ["No model predictions available"]
            consensus = 0.0
            avg_confidence = 0.0
            if getattr(settings, "diagnostics_enabled", True):
                logger.info(
                    "reasoning_hold_exit",
                    symbol=request.symbol,
                    reason="no_model_predictions",
                    consensus=float(consensus),
                    strong_thresh=None,
                    mild_thresh=None,
                    vol=None,
                    avg_confidence=float(avg_confidence),
                    total_models=0,
                    message="Step 5 produced HOLD due to missing model predictions.",
                )
        else:
            # Separate classifier and regressor predictions
            # Regressors predict prices directly and are generally more reliable for price direction
            classifier_predictions = [
                p for p in model_predictions 
                if p.get("model_type", "").lower() == "classifier"
            ]
            regressor_predictions = [
                p for p in model_predictions 
                if p.get("model_type", "").lower() == "regressor"
            ]
            
            # Calculate consensus for each type
            classifier_consensus = 0.0
            regressor_consensus = 0.0
            classifier_confidence = 0.0
            regressor_confidence = 0.0
            
            if classifier_predictions:
                classifier_weight = 0.0
                classifier_sum = 0.0
                for p in classifier_predictions:
                    prediction = p.get("prediction", 0.0)
                    confidence = max(0.0, min(1.0, p.get("confidence", 0.5)))
                    classifier_sum += prediction * confidence
                    classifier_weight += confidence
                if classifier_weight > 0:
                    classifier_consensus = classifier_sum / classifier_weight
                    classifier_confidence = classifier_weight / len(classifier_predictions)
            
            if regressor_predictions:
                regressor_weight = 0.0
                regressor_sum = 0.0
                for p in regressor_predictions:
                    prediction = p.get("prediction", 0.0)
                    confidence = max(0.0, min(1.0, p.get("confidence", 0.5)))
                    regressor_sum += prediction * confidence
                    regressor_weight += confidence
                if regressor_weight > 0:
                    regressor_consensus = regressor_sum / regressor_weight
                    regressor_confidence = regressor_weight / len(regressor_predictions)
            
            # Combine consensus: prefer regressors if available (they predict prices directly)
            # If both exist, use weighted average with higher weight for regressors (2:1 ratio)
            if regressor_predictions and classifier_predictions:
                # Both types present: weighted average favoring regressors
                regressor_weight_ratio = 2.0  # Regressors get 2x weight
                total_combined_weight = regressor_confidence * regressor_weight_ratio + classifier_confidence
                if total_combined_weight > 0:
                    consensus = (
                        regressor_consensus * regressor_confidence * regressor_weight_ratio +
                        classifier_consensus * classifier_confidence
                    ) / total_combined_weight
                    avg_confidence = total_combined_weight / (regressor_weight_ratio + 1.0)
                else:
                    consensus = (regressor_consensus + classifier_consensus) / 2.0
                    avg_confidence = (regressor_confidence + classifier_confidence) / 2.0
                evidence_detail = f"Regressor consensus: {regressor_consensus:.2f} (weight: {regressor_weight_ratio}x), Classifier consensus: {classifier_consensus:.2f}"
            elif regressor_predictions:
                # Only regressors available
                consensus = regressor_consensus
                avg_confidence = regressor_confidence
                evidence_detail = f"Regressor consensus: {consensus:.2f} ({len(regressor_predictions)} models)"
            elif classifier_predictions:
                # Only classifiers available
                consensus = classifier_consensus
                avg_confidence = classifier_confidence
                evidence_detail = f"Classifier consensus: {consensus:.2f} ({len(classifier_predictions)} models)"
            else:
                # Fallback: model_type missing or not classifier/regressor – treat all as one group
                total_weight = 0.0
                weighted_sum = 0.0
                for p in model_predictions:
                    prediction = p.get("prediction", 0.0)
                    confidence = max(0.0, min(1.0, p.get("confidence", 0.5)))
                    weighted_sum += prediction * confidence
                    total_weight += confidence
                if total_weight > 0:
                    consensus = weighted_sum / total_weight
                    avg_confidence = total_weight / len(model_predictions)
                else:
                    consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
                    # Use mean of confidences (default 0.5 when missing) so step 5 never forces 0
                    avg_confidence = sum(
                        max(0.0, min(1.0, p.get("confidence", 0.5)))
                        for p in model_predictions
                    ) / len(model_predictions) if model_predictions else 0.0
                evidence_detail = f"Combined consensus: {consensus:.2f} (fallback calculation)"
            
            # Adaptive consensus thresholds by volatility (when vol available); else fixed
            features = request.market_context.get("features", {})
            vol = features.get("volatility")
            if vol is not None:
                if vol > 5:
                    strong_thresh, mild_thresh = 0.45, 0.20
                elif vol < 1.5:
                    strong_thresh, mild_thresh = 0.35, 0.15
                else:
                    strong_thresh, mild_thresh = 0.40, 0.18
            else:
                strong_thresh, mild_thresh = 0.40, 0.18

            decision_code = "HOLD"
            if consensus > strong_thresh:
                decision_code = "STRONG_BUY"
                conclusion = "STRONG_BUY - High confidence bullish signal"
            elif consensus > mild_thresh:
                decision_code = "BUY"
                conclusion = "BUY - Moderate bullish signal"
            elif consensus < -strong_thresh:
                decision_code = "STRONG_SELL"
                conclusion = "STRONG_SELL - High confidence bearish signal"
            elif consensus < -mild_thresh:
                decision_code = "SELL"
                conclusion = "SELL - Moderate bearish signal"
            else:
                conclusion = "HOLD - Mixed signals, waiting for clearer direction"

            if getattr(settings, "diagnostics_enabled", True):
                logger.info(
                    "reasoning_stage5_decision",
                    symbol=request.symbol,
                    decision=decision_code,
                    consensus=float(consensus),
                    strong_thresh=float(strong_thresh),
                    mild_thresh=float(mild_thresh),
                    vol=float(vol) if vol is not None else None,
                    avg_confidence=float(avg_confidence),
                    total_models=len(model_predictions),
                    classifiers=len(classifier_predictions),
                    regressors=len(regressor_predictions),
                )
                if decision_code == "HOLD":
                    logger.info(
                        "reasoning_hold_exit",
                        symbol=request.symbol,
                        reason="consensus_in_hold_band",
                        consensus=float(consensus),
                        strong_thresh=float(strong_thresh),
                        mild_thresh=float(mild_thresh),
                        vol=float(vol) if vol is not None else None,
                        avg_confidence=float(avg_confidence),
                        total_models=len(model_predictions),
                    )
            
            evidence = [
                f"Final consensus: {consensus:.2f} (weighted avg confidence: {avg_confidence:.2f})",
                evidence_detail,
                f"Based on {len(previous_steps)} analysis steps",
                f"Total models: {len(model_predictions)} ({len(classifier_predictions)} classifiers, {len(regressor_predictions)} regressors)"
            ]

        # Calculate data freshness from market data timestamps
        data_freshness_seconds = None
        market_timestamp = request.market_context.get("timestamp")
        if market_timestamp:
            try:
                if isinstance(market_timestamp, str):
                    market_time = datetime.fromisoformat(market_timestamp.replace('Z', '+00:00'))
                else:
                    market_time = market_timestamp
                data_freshness_seconds = int((datetime.utcnow() - market_time).total_seconds())
            except (ValueError, TypeError):
                pass

        return ReasoningStep(
            step_number=5,
            step_name="Decision Synthesis",
            description=conclusion,
            evidence=evidence,
            confidence=avg_confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds
        )
    
    async def _step6_confidence_calibration(self, steps: List[ReasoningStep], model_predictions: List[Dict[str, Any]]) -> ReasoningStep:
        """Step 6: Calibrate final confidence using weighted average and consistency adjustment.

        When learning is disabled, calibration uses only step confidences and a consistency
        adjustment (no historical accuracy). If learning is enabled, historical calibration
        could be integrated here (e.g. w * historical_accuracy + (1-w) * raw_confidence).
        """

        # Weighted average with step importance weights
        # Steps 3 (model consensus) and 5 (decision synthesis) get higher weights
        step_weights = {
            1: 0.1,  # Situational assessment
            2: 0.1,  # Historical context
            3: 0.3,  # Model consensus (most important)
            4: 0.1,  # Risk assessment
            5: 0.3,  # Decision synthesis (most important)
            6: 0.1   # Confidence calibration (meta-step)
        }

        weighted_sum = sum(
            step.confidence * step_weights.get(step.step_number, 0.1)
            for step in steps
        )
        total_weight = sum(step_weights.get(step.step_number, 0.1) for step in steps)
        base_confidence = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Consistency adjustment (less aggressive)
        if steps:
            confidence_range = max(step.confidence for step in steps) - min(step.confidence for step in steps)
            # Use consistency as a small adjustment factor, not a multiplier
            consistency_adjustment = max(0.9, 1.0 - (confidence_range * 0.2))  # Max 10% penalty
        else:
            consistency_adjustment = 1.0

        final_confidence = base_confidence * consistency_adjustment
        reasoning_only_confidence = final_confidence

        # Apply model_avg floor only when reasoning confidence is meaningfully positive
        if model_predictions:
            model_confidences = [max(0.0, min(1.0, float(p.get("confidence", 0)))) for p in model_predictions]
            model_avg = sum(model_confidences) / len(model_confidences) if model_confidences else 0.0
            if reasoning_only_confidence > 0.1 and model_avg > 0:
                final_confidence = max(final_confidence, model_avg * 0.8)
            # Unanimous HOLD: all models agree on neutral (confidence 0). Avoid showing 0% in UI.
            if model_avg == 0 and model_confidences:
                final_confidence = max(final_confidence, 0.5)

        # Detect fallback scenario for logging/diagnostics
        is_fallback_scenario = not model_predictions or all(
            p.get("confidence", 0) == 0 for p in model_predictions
        )

        # Ensure final confidence is in valid range
        final_confidence = max(0.0, min(1.0, final_confidence))

        # Log confidence calculation for debugging
        step_confidences = {step.step_number: step.confidence for step in steps}
        logger.info(
            "confidence_calibration_completed",
            step_confidences=step_confidences,
            base_confidence=base_confidence,
            consistency_adjustment=consistency_adjustment,
            final_confidence=final_confidence,
            is_fallback_scenario=is_fallback_scenario,
            model_predictions_count=len(model_predictions),
            message="Confidence calibration step completed"
        )

        return ReasoningStep(
            step_number=6,
            step_name="Confidence Calibration",
            description=f"Final confidence: {final_confidence:.2f}",
            evidence=[
                f"Weighted base confidence: {base_confidence:.2f}",
                f"Consistency adjustment: {consistency_adjustment:.2f}",
                f"Final confidence: {final_confidence:.2f}",
                f"Fallback scenario: {is_fallback_scenario}"
            ],
            confidence=final_confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=None,  # Meta-step, no direct market data access
            similarity_score=None,
            feature_quality_score=None
        )
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": "up",
            "vector_store_available": self.vector_store is not None
        }

