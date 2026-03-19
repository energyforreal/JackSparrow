"""
MCP Model Registry.

Manages all ML model nodes and implements MCP Model Protocol.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import time
import asyncio
import structlog
import uuid

from pydantic import BaseModel

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction
from agent.models.advanced_consensus import AdvancedConsensusEngine, ConsensusConfig, ModelPrediction as ConsensusModelPrediction
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    ModelPredictionRequestEvent,
    ModelPredictionEvent,
    ModelPredictionCompleteEvent,
    EventType
)

logger = structlog.get_logger()


class MCPModelResponse(BaseModel):
    """MCP Model Protocol response."""
    request_id: str
    predictions: List[MCPModelPrediction]
    consensus_prediction: float  # Weighted average
    consensus_confidence: float
    healthy_models: int
    total_models: int
    timestamp: datetime


class NoModelsRegisteredError(Exception):
    """Raised when no ML models are registered in the model registry."""


class NoHealthyModelPredictionsError(Exception):
    """Raised when no acceptable model predictions are available for consensus."""


class MCPModelRegistry:
    """MCP Model Registry managing all model nodes."""
    
    def __init__(self):
        """Initialize model registry."""
        self.models: Dict[str, MCPModelNode] = {}
        self.model_weights: Dict[str, float] = {}
        self._pending_predictions: Dict[str, List[MCPModelPrediction]] = {}  # Track pending predictions by request_id
        # Health tracking
        self._prediction_latencies: Dict[str, List[float]] = {}  # Track prediction latencies per model
        self._prediction_errors: Dict[str, int] = {}  # Track error counts per model
        # Advanced consensus engine
        self.consensus_engine = AdvancedConsensusEngine(ConsensusConfig())
        self._outcome_history: Dict[str, float] = {}  # Store outcomes for learning
        self._prediction_successes: Dict[str, int] = {}  # Track success counts per model
        self._pending_models: Dict[str, MCPModelNode] = {}
        self._max_latency_history: int = 100  # Keep last 100 latencies per model
        self._discovery_summary: Dict[str, Any] = {
            "discovery_attempted": False,
            "discovered_models": 0,
            "failed_models": 0,
            "failed_files": [],
            "last_error_messages": [],
            "last_attempt_at": None,
        }
    
    async def initialize(self):
        """Initialize model registry."""
        # Models will be registered via model discovery.
        # Do NOT subscribe to MODEL_PREDICTION_REQUEST here: the orchestrator is the single
        # authoritative handler for prediction requests and calls the registry internally.
        # Duplicate subscription caused DecisionReadyEvent from a second path without
        # market_context.features (e.g. volatility), leading to trading handler skipping trades.
    
    async def shutdown(self):
        """Shutdown all models."""
        for model in self.models.values():
            try:
                # Models may have cleanup methods
                pass
            except Exception as e:
                logger.error(
                    "model_registry_shutdown_failed",
                    model_name=model.model_name,
                    error=str(e),
                    exc_info=True
                )
    
    def register_model(self, model: MCPModelNode, weight: Optional[float] = None):
        """Register model node.
        
        Args:
            model: Model node to register
            weight: Optional initial weight. If None, will use equal weight or 
                   performance-based weight if available.
        """
        if model.model_name in self._pending_models:
            del self._pending_models[model.model_name]
        self.models[model.model_name] = model
        
        if weight is not None:
            self.model_weights[model.model_name] = weight
        else:
            # Use equal weight initially (will be updated by learning system based on performance)
            if self.models:
                equal_weight = 1.0 / len(self.models)
            else:
                equal_weight = 1.0
            self.model_weights[model.model_name] = equal_weight
        
        # Normalize weights
        self._normalize_weights()

    def get_model(self, model_name: str) -> Optional[MCPModelNode]:
        """Retrieve a registered model by name."""
        return self.models.get(model_name)

    def list_models(self) -> List[str]:
        """List names of all registered models."""
        return list(self.models.keys())

    def get_required_feature_names(self) -> List[str]:
        """Return union of feature names required by all registered models (e.g. v4 metadata order).
        Used so the orchestrator requests exactly the features models need, preserving order per model.
        """
        seen: set = set()
        out: List[str] = []
        for model in self.models.values():
            info = model.get_model_info()
            names = info.get("features_required") or info.get("feature_list") or []
            for name in names:
                if name and name not in seen:
                    seen.add(name)
                    out.append(name)
        return out if out else []

    def unregister_model(self, model_name: str):
        """Unregister model node."""
        if model_name in self.models:
            del self.models[model_name]
        if model_name in self.model_weights:
            del self.model_weights[model_name]
        self._normalize_weights()
    
    def record_discovery_summary(
        self,
        discovered_models: List[str],
        failed_files: List[str],
        error_messages: List[str],
        discovery_attempted: bool = True,
    ) -> None:
        """Persist latest discovery attempt summary."""
        self._discovery_summary = {
            "discovery_attempted": discovery_attempted,
            "discovered_models": len(discovered_models),
            "failed_models": len(failed_files),
            "failed_files": failed_files[:5],
            "last_error_messages": error_messages[-5:],  # keep recent
            "last_attempt_at": datetime.utcnow().isoformat() if discovery_attempted else None,
            "pending_models": len(self._pending_models),
            "pending_model_names": list(self._pending_models.keys())[:10],
        }
    
    def _normalize_weights(self):
        """Normalize model weights to sum to 1.0."""
        if not self.model_weights:
            return
        
        total_weight = sum(self.model_weights.values())
        if total_weight > 0:
            self.model_weights = {
                name: weight / total_weight
                for name, weight in self.model_weights.items()
            }
    
    async def get_predictions(self, request: MCPModelRequest) -> MCPModelResponse:
        """Get predictions from all healthy models."""
        
        if not self.models:
            logger.error(
                "model_registry_no_models_registered",
                request_id=request.request_id,
                message="No ML models are registered in MCPModelRegistry. Cannot generate predictions."
            )
            raise NoModelsRegisteredError(
                "No ML models are registered. Model discovery may have failed or loaded zero models."
            )
        
        # Get predictions from all models in parallel with timeout per model
        predictions: List[MCPModelPrediction] = []
        failed_models = []
        
        # Timeout per model: 5 seconds (prevents slow models from blocking others)
        MODEL_PREDICTION_TIMEOUT = 5.0
        
        tasks = []
        for model in self.models.values():
            # Wrap each prediction with timeout
            task = asyncio.wait_for(
                self._get_prediction_safe(model, request),
                timeout=MODEL_PREDICTION_TIMEOUT
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, MCPModelPrediction):
                predictions.append(result)
            elif isinstance(result, asyncio.TimeoutError):
                # Model prediction timed out
                model_name = list(self.models.keys())[i] if i < len(self.models) else "unknown"
                failed_models.append(model_name)
                logger.warning(
                    "model_registry_prediction_timeout",
                    model_name=model_name,
                    timeout=MODEL_PREDICTION_TIMEOUT,
                    message="Model prediction timed out - model will be excluded from consensus"
                )
                # Create a degraded prediction for timeout
                predictions.append(MCPModelPrediction(
                    model_name=model_name,
                    model_version="unknown",
                    prediction=0.0,
                    confidence=0.0,
                    reasoning=f"Model prediction timed out after {MODEL_PREDICTION_TIMEOUT}s",
                    features_used=[],
                    feature_importance={},
                    computation_time_ms=MODEL_PREDICTION_TIMEOUT * 1000,
                    health_status="degraded"
                ))
            elif isinstance(result, Exception):
                # Exception was raised despite _get_prediction_safe wrapper
                # This should be rare, but handle it gracefully
                model_name = list(self.models.keys())[i] if i < len(self.models) else "unknown"
                failed_models.append(model_name)
                logger.error(
                    "model_registry_prediction_exception",
                    model_name=model_name,
                    error=str(result),
                    error_type=type(result).__name__,
                    message="Exception raised during prediction despite safe wrapper - model will be excluded from consensus",
                    exc_info=True
                )
                # Create a degraded prediction to maintain consistency
                predictions.append(MCPModelPrediction(
                    model_name=model_name,
                    model_version="unknown",
                    prediction=0.0,
                    confidence=0.0,
                    reasoning=f"Exception during prediction: {str(result)}",
                    features_used=[],
                    feature_importance={},
                    computation_time_ms=0.0,
                    health_status="degraded"
                ))
        
        # Log summary of prediction results
        if failed_models:
            logger.warning(
                "model_registry_some_models_failed",
                request_id=request.request_id,
                failed_models=failed_models,
                total_models=len(self.models),
                successful_predictions=len([p for p in predictions if p.health_status == "healthy"]),
                message=f"{len(failed_models)} model(s) failed to predict, continuing with remaining models"
            )
        
        # Health validation: If a model successfully made a prediction, it should be considered healthy
        # Update health_status for successful predictions
        for pred in predictions:
            # If prediction was successful (has non-zero confidence or valid prediction value)
            # and health_status is not "healthy", update it
            if pred.health_status != "healthy":
                # Check if prediction appears successful
                is_successful = (
                    pred.confidence > 0.0 or 
                    abs(pred.prediction) > 0.0 or
                    pred.computation_time_ms < 10000  # Reasonable computation time
                )
                
                if is_successful and pred.health_status in ["unknown", "degraded"]:
                    # Update the model's health status if we have access to it
                    model = self.models.get(pred.model_name)
                    if model and hasattr(model, 'health_status'):
                        old_status = model.health_status
                        model.health_status = "healthy"
                        pred.health_status = "healthy"
                        logger.info(
                            "model_health_status_validated",
                            model_name=pred.model_name,
                            old_status=old_status,
                            new_status="healthy",
                            reason="Successful prediction indicates healthy model",
                            message="Updated model health_status based on successful prediction"
                        )
        
        # Diagnostic logging: Log health status for all predictions before filtering
        if predictions:
            prediction_health_statuses = [
                {
                    "model_name": pred.model_name,
                    "health_status": pred.health_status,
                    "prediction": pred.prediction,
                    "confidence": pred.confidence
                }
                for pred in predictions
            ]
            logger.info(
                "model_predictions_health_status",
                request_id=request.request_id,
                total_predictions=len(predictions),
                prediction_health_statuses=prediction_health_statuses,
                message="Health status of all predictions before filtering"
            )
        
        # Log model health status before prediction attempts
        model_health_before = {}
        for model_name, model in self.models.items():
            try:
                health_info = await model.get_health_status()
                model_health_before[model_name] = health_info.get("status", "unknown")
            except Exception as e:
                model_health_before[model_name] = f"error: {str(e)}"
        
        if model_health_before:
            logger.debug(
                "model_health_status_before_predictions",
                request_id=request.request_id,
                model_health_statuses=model_health_before,
                message="Model health status before prediction attempts"
            )
        
        # Filter predictions by health status with strict requirements
        # Priority: healthy > unknown (if model loaded) > degraded (with reduced weight).
        # If no acceptable predictions remain, treat as a hard error instead of
        # fabricating a zero-confidence consensus.
        healthy_predictions = [
            pred for pred in predictions
            if pred.health_status == "healthy"
        ]
        
        # Fallback: If no healthy predictions, check for "unknown" status
        # (models that loaded but haven't been marked healthy yet)
        if not healthy_predictions:
            unknown_predictions = [
                pred for pred in predictions
                if pred.health_status == "unknown"
            ]
            if unknown_predictions:
                logger.info(
                    "model_predictions_using_unknown_status",
                    request_id=request.request_id,
                    unknown_count=len(unknown_predictions),
                    message="No healthy predictions, using 'unknown' status predictions as fallback"
                )
                healthy_predictions = unknown_predictions
        
        # Last resort: Use degraded predictions with reduced weight
        if not healthy_predictions:
            degraded_predictions = [
                pred for pred in predictions
                if pred.health_status == "degraded"
            ]
            if degraded_predictions:
                logger.warning(
                    "model_predictions_using_degraded_status",
                    request_id=request.request_id,
                    degraded_count=len(degraded_predictions),
                    message="No healthy/unknown predictions, using 'degraded' status predictions with reduced weight"
                )
                healthy_predictions = degraded_predictions
        
        # If no acceptable predictions remain, raise an explicit error so callers
        # can stop before attempting to generate a trading decision.
        if predictions and not healthy_predictions:
            filtered_out = [
                {
                    "model_name": pred.model_name,
                    "health_status": pred.health_status,
                    "reason": f"health_status='{pred.health_status}' not acceptable",
                }
                for pred in predictions
            ]
            logger.error(
                "model_predictions_all_filtered_out",
                request_id=request.request_id,
                total_predictions=len(predictions),
                healthy_predictions=len(healthy_predictions),
                filtered_predictions=filtered_out,
                message="All predictions filtered out - no acceptable predictions available",
            )
            raise NoHealthyModelPredictionsError(
                "All model predictions were filtered out due to unacceptable health status."
            )

        if not healthy_predictions:
            # No predictions at all (e.g., every model failed fast). Treat this as
            # a hard error rather than fabricating a neutral consensus.
            logger.error(
                "model_predictions_none_available",
                request_id=request.request_id,
                total_models=len(self.models),
                message="No model predictions are available for consensus calculation.",
            )
            raise NoHealthyModelPredictionsError(
                "No model predictions are available for consensus calculation."
            )

        # Calculate advanced consensus using sophisticated algorithms
        try:
            # Convert MCP predictions to consensus engine format
            consensus_predictions = []
            for pred in healthy_predictions:
                consensus_pred = ConsensusModelPrediction(
                    model_name=pred.model_name,
                    prediction=pred.prediction,
                    confidence=pred.confidence,
                    timestamp=datetime.utcnow(),
                    model_type=self.models[pred.model_name].model_type
                    if pred.model_name in self.models
                    else "unknown",
                    feature_importance=getattr(pred, "feature_importance", None),
                    metadata={
                        "health_status": pred.health_status,
                        "computation_time_ms": getattr(pred, "computation_time_ms", 0),
                        "model_version": getattr(pred, "model_version", "unknown"),
                    },
                )
                consensus_predictions.append(consensus_pred)

            # Extract market context for regime detection
            market_context = request.context if hasattr(request, "context") else {}
            current_price = market_context.get("current_price", 50000.0)
            market_context.update(
                {
                    "volatility": market_context.get("volatility", 0.02),
                    "trend_strength": market_context.get("trend_strength", 0.5),
                    "volume_ratio": market_context.get("volume_ratio", 1.0),
                }
            )

            # Calculate advanced consensus
            consensus_result = await self.consensus_engine.calculate_consensus(
                predictions=consensus_predictions,
                market_context=market_context,
                consensus_method="adaptive",
            )

            consensus_prediction = consensus_result.final_prediction
            consensus_confidence = consensus_result.confidence

            # Log advanced consensus details
            logger.info(
                "advanced_consensus_calculated",
                request_id=request.request_id,
                method=consensus_result.consensus_method,
                final_prediction=round(consensus_prediction, 4),
                confidence=round(consensus_confidence, 4),
                model_weights={
                    k: round(v, 3) for k, v in consensus_result.model_weights.items()
                },
                reasoning=consensus_result.reasoning,
                risk_level=consensus_result.risk_assessment.get("risk_level", "unknown"),
            )

        except Exception as e:
            logger.error(
                "advanced_consensus_failed",
                request_id=request.request_id,
                error=str(e),
                message="Falling back to simple consensus based on available model predictions.",
            )

            # Fallback to simple average that is still based on actual model
            # predictions (never fabricating a zero-confidence decision).
            consensus_prediction = sum(
                pred.prediction for pred in healthy_predictions
            ) / len(healthy_predictions)
            consensus_confidence = sum(
                pred.confidence for pred in healthy_predictions
            ) / len(healthy_predictions)

        return MCPModelResponse(
            request_id=request.request_id,
            predictions=predictions,
            consensus_prediction=consensus_prediction,
            consensus_confidence=consensus_confidence,
            healthy_models=len(healthy_predictions),
            total_models=len(self.models),
            timestamp=datetime.utcnow(),
        )

    async def record_prediction_outcome(self, request_id: str, actual_outcome: float,
                                      market_context: Optional[Dict[str, Any]] = None):
        """
        Record the actual outcome of a prediction for learning.

        Args:
            request_id: The request ID from the original prediction
            actual_outcome: The actual market outcome (price change, P&L, etc.)
            market_context: Market context at the time of outcome
        """
        if request_id in self._outcome_history:
            logger.warning("outcome_already_recorded", request_id=request_id)
            return

        # Store outcome for potential future use
        self._outcome_history[request_id] = {
            "outcome": actual_outcome,
            "timestamp": datetime.utcnow(),
            "market_context": market_context or {}
        }

        # If we have the original predictions, use them for learning
        if request_id in self._pending_predictions:
            predictions = self._pending_predictions[request_id]

            # Convert to consensus engine format and record outcome
            consensus_predictions = []
            for pred in predictions:
                consensus_pred = ConsensusModelPrediction(
                    model_name=pred.model_name,
                    prediction=pred.prediction,
                    confidence=pred.confidence,
                    timestamp=getattr(pred, 'timestamp', datetime.utcnow()),
                    model_type=self.models[pred.model_name].model_type if pred.model_name in self.models else "unknown"
                )
                consensus_predictions.append(consensus_pred)

            # Record outcome for learning
            await self.consensus_engine.record_outcome(
                predictions=consensus_predictions,
                actual_outcome=actual_outcome,
                market_context=market_context or {}
            )

            # Clean up pending predictions after some time
            if len(self._pending_predictions) > 1000:  # Keep last 1000 for memory management
                # Remove oldest entries
                sorted_requests = sorted(self._pending_predictions.keys(),
                                       key=lambda x: self._outcome_history.get(x, {}).get("timestamp", datetime.min))
                to_remove = sorted_requests[:-1000]
                for req_id in to_remove:
                    self._pending_predictions.pop(req_id, None)

            logger.info("prediction_outcome_recorded",
                       request_id=request_id,
                       actual_outcome=round(actual_outcome, 4),
                       models_used=len(consensus_predictions),
                       market_context_keys=list(market_context.keys()) if market_context else [])

    async def _get_prediction_safe(
        self,
        model: MCPModelNode,
        request: MCPModelRequest
    ) -> Optional[MCPModelPrediction]:
        """Safely get prediction from model."""
        import time
        start_time = time.time()
        success = False
        
        try:
            prediction = await model.predict(request)
            success = True
            latency_ms = (time.time() - start_time) * 1000
            
            # Record successful prediction
            self._record_prediction_result(model.model_name, latency_ms, True)
            
            return prediction
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            
            # Record failed prediction
            self._record_prediction_result(model.model_name, latency_ms, False)
            
            logger.error(
                "model_registry_prediction_failed",
                model_name=model.model_name,
                error=str(e),
                exc_info=True
            )
            # Return degraded prediction
            return MCPModelPrediction(
                model_name=model.model_name,
                model_version=model.model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"Model error: {str(e)}",
                features_used=[],
                feature_importance={},
                computation_time_ms=latency_ms,
                health_status="degraded"
            )
    
    def update_model_weight(self, model_name: str, weight: float):
        """Update model weight based on performance metrics.
        
        Args:
            model_name: Name of the model
            weight: New weight (typically calculated from accuracy and profit)
        """
        if model_name in self.models:
            self.model_weights[model_name] = weight
            self._normalize_weights()
    
    def update_weights_from_performance(self, performance_weights: Dict[str, float]):
        """Update all model weights from performance metrics.
        
        Args:
            performance_weights: Dictionary mapping model names to performance-based weights
        """
        for model_name, weight in performance_weights.items():
            if model_name in self.models:
                self.model_weights[model_name] = weight
        self._normalize_weights()
    
    async def _handle_prediction_request_event(self, event: ModelPredictionRequestEvent):
        """Handle model prediction request event.
        
        Args:
            event: Model prediction request event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            features = payload.get("features", {})
            context = payload.get("context", {})
            require_explanation = payload.get("require_explanation", True)
            
            # Create MCP request
            request = MCPModelRequest(
                request_id=str(uuid.uuid4()),
                features=list(features.values()),
                context=context,
                require_explanation=require_explanation
            )
            
            # Track predictions for this request
            self._pending_predictions[request.request_id] = []
            
            # Get predictions from all models
            response = await self.get_predictions(request)
            
            # Emit individual prediction events
            for prediction in response.predictions:
                await self._emit_prediction_event(event, prediction)
            
            # Emit complete event when all done
            await self._emit_prediction_complete_event(event, response)
            
            # Clean up
            if request.request_id in self._pending_predictions:
                del self._pending_predictions[request.request_id]
                
        except Exception as e:
            logger.error(
                "model_prediction_request_event_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def _emit_prediction_event(self, request_event: ModelPredictionRequestEvent, prediction: MCPModelPrediction):
        """Emit individual model prediction event.
        
        Args:
            request_event: Original prediction request event
            prediction: Model prediction
        """
        try:
            event = ModelPredictionEvent(
                source="model_registry",
                correlation_id=request_event.event_id,
                payload={
                    "model_name": prediction.model_name,
                    "model_version": prediction.model_version,
                    "prediction": prediction.prediction,
                    "confidence": prediction.confidence,
                    "reasoning": prediction.reasoning,
                    "features_used": prediction.features_used,
                    "feature_importance": prediction.feature_importance,
                    "computation_time_ms": prediction.computation_time_ms,
                    "health_status": prediction.health_status
                }
            )
            
            await event_bus.publish(event)
            
            logger.debug(
                "model_prediction_event_emitted",
                model_name=prediction.model_name,
                prediction=prediction.prediction,
                confidence=prediction.confidence,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "model_prediction_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def _emit_prediction_complete_event(self, request_event: ModelPredictionRequestEvent, response: MCPModelResponse):
        """Emit model prediction complete event.
        
        Args:
            request_event: Original prediction request event
            response: Model response with all predictions
        """
        try:
            # Convert predictions to dict format
            predictions_dict = [
                {
                    "model_name": pred.model_name,
                    "model_version": pred.model_version,
                    "prediction": pred.prediction,
                    "confidence": pred.confidence,
                    "reasoning": pred.reasoning,
                    "health_status": pred.health_status
                }
                for pred in response.predictions
            ]
            
            event = ModelPredictionCompleteEvent(
                source="model_registry",
                correlation_id=request_event.event_id,
                payload={
                    "symbol": request_event.payload.get("symbol"),
                    "predictions": predictions_dict,
                    "consensus_signal": response.consensus_prediction,
                    "consensus_confidence": response.consensus_confidence,
                    "timestamp": response.timestamp
                }
            )
            
            await event_bus.publish(event)
            
            logger.info(
                "model_prediction_complete_event_emitted",
                symbol=request_event.payload.get("symbol"),
                prediction_count=len(predictions_dict),
                consensus_signal=response.consensus_prediction,
                consensus_confidence=response.consensus_confidence,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "model_prediction_complete_event_emit_failed",
                error=str(e),
                exc_info=True
            )

    def add_pending_model(self, model: MCPModelNode):
        """Store model node in pending cache for manual activation."""
        self._pending_models[model.model_name] = model
        logger.info(
            "model_pending_registration",
            model_name=model.model_name,
            model_type=model.model_type
        )

    def list_pending_models(self) -> List[str]:
        """Return names of pending models awaiting registration."""
        return list(self._pending_models.keys())

    def register_pending_models(self, model_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Register pending models by name (or all pending if none specified)."""
        targets = model_names or list(self._pending_models.keys())
        results = {
            "registered": [],
            "not_found": []
        }
        for name in targets:
            model = self._pending_models.pop(name, None)
            if not model:
                results["not_found"].append(name)
                continue
            self.register_model(model)
            results["registered"].append(name)
            logger.info(
                "pending_model_registered",
                model_name=name
            )
        return results
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of all models."""
        
        health_statuses = {}
        healthy_count = 0
        
        for model_name, model in self.models.items():
            try:
                # Get base health status from model
                status = await model.get_health_status()
                
                # Enhance with registry tracking data
                latencies = self._prediction_latencies.get(model_name, [])
                errors = self._prediction_errors.get(model_name, 0)
                successes = self._prediction_successes.get(model_name, 0)
                total_predictions = errors + successes
                
                # Calculate metrics
                avg_latency_ms = sum(latencies) / len(latencies) if latencies else None
                max_latency_ms = max(latencies) if latencies else None
                error_rate = errors / total_predictions if total_predictions > 0 else 0.0
                
                # Determine overall health status
                model_health = status.get("status", "unknown")
                
                # Consider model unhealthy if:
                # - Model reports unhealthy
                # - Error rate > 50%
                # - Average latency > 5000ms (5 seconds)
                if model_health != "healthy":
                    overall_status = "unhealthy"
                elif error_rate > 0.5:
                    overall_status = "degraded"
                elif avg_latency_ms and avg_latency_ms > 5000:
                    overall_status = "degraded"
                else:
                    overall_status = "healthy"
                    if model_health == "healthy":
                        healthy_count += 1
                
                # Build comprehensive status
                health_statuses[model_name] = {
                    "status": overall_status,
                    "model_status": model_health,
                    "model_loaded": status.get("model_loaded", False),
                    "prediction_metrics": {
                        "total_predictions": total_predictions,
                        "successes": successes,
                        "errors": errors,
                        "error_rate": round(error_rate, 4),
                        "avg_latency_ms": round(avg_latency_ms, 2) if avg_latency_ms else None,
                        "max_latency_ms": round(max_latency_ms, 2) if max_latency_ms else None,
                        "recent_latencies": latencies[-10:] if latencies else []  # Last 10 latencies
                    },
                    "model_info": model.get_model_info()
                }
            except Exception as e:
                health_statuses[model_name] = {
                    "status": "unknown",
                    "error": str(e),
                    "prediction_metrics": {
                        "total_predictions": 0,
                        "successes": 0,
                        "errors": 0,
                        "error_rate": 0.0
                    }
                }
        
        # Determine overall status
        # If no models are loaded, return "unknown" (acceptable in paper trading mode)
        # If all models are healthy, return "up"
        # If some models are healthy, return "degraded"
        # If no models are healthy but models exist, return "degraded" (not "down") so UI shows warning
        # - 0 healthy often means "no predictions run yet" rather than total failure
        if len(self.models) == 0:
            registry_health = "unknown"
            status = "unknown"
        elif healthy_count == len(self.models):
            registry_health = "healthy"
            status = "up"
        elif healthy_count > 0:
            registry_health = "degraded"
            status = "degraded"
        else:
            # All models exist but none counted healthy (e.g. no predictions yet or health check pending)
            registry_health = "degraded"
            status = "degraded"
        
        # Update discovery summary to reflect actual registry state if there's a discrepancy
        # This ensures the discovery summary is accurate
        if len(self.models) > 0 and self._discovery_summary.get("discovered_models", 0) != len(self.models):
            self._discovery_summary["discovered_models"] = len(self.models)
            # If we have models but discovery summary says discovery wasn't attempted, update it
            if not self._discovery_summary.get("discovery_attempted", False):
                self._discovery_summary["discovery_attempted"] = True
        
        return {
            "status": status,  # Standard status field for health checks ("up", "degraded", "down", "unknown")
            "total_models": len(self.models),  # Always use actual registry count
            "healthy_models": healthy_count,
            "unhealthy_models": len(self.models) - healthy_count,
            "model_statuses": health_statuses,
            "registry_health": registry_health,  # Keep for backward compatibility
            "discovery": self._discovery_summary,
        }
    
    def _record_prediction_result(self, model_name: str, latency_ms: float, success: bool):
        """Record prediction result for health tracking.
        
        Args:
            model_name: Name of the model
            latency_ms: Prediction latency in milliseconds
            success: Whether prediction succeeded
        """
        # Initialize tracking if needed
        if model_name not in self._prediction_latencies:
            self._prediction_latencies[model_name] = []
            self._prediction_errors[model_name] = 0
            self._prediction_successes[model_name] = 0
        
        # Record latency
        self._prediction_latencies[model_name].append(latency_ms)
        # Keep only recent latencies
        if len(self._prediction_latencies[model_name]) > self._max_latency_history:
            self._prediction_latencies[model_name] = self._prediction_latencies[model_name][-self._max_latency_history:]
        
        # Record success/error
        if success:
            self._prediction_successes[model_name] += 1
        else:
            self._prediction_errors[model_name] += 1

