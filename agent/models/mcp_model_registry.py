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
        # Models will be registered via model discovery
        # Register event handler
        event_bus.subscribe(EventType.MODEL_PREDICTION_REQUEST, self._handle_prediction_request_event)
    
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
            return MCPModelResponse(
                request_id=request.request_id,
                predictions=[],
                consensus_prediction=0.0,
                consensus_confidence=0.0,
                healthy_models=0,
                total_models=0,
                timestamp=datetime.utcnow()
            )
        
        # Get predictions from all models in parallel
        predictions: List[MCPModelPrediction] = []
        
        tasks = []
        for model in self.models.values():
            tasks.append(self._get_prediction_safe(model, request))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, MCPModelPrediction):
                predictions.append(result)
            elif isinstance(result, Exception):
                logger.error(
                    "model_registry_prediction_error",
                    error=str(result),
                    exc_info=True
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
        
        # Filter predictions by health status with fallback logic
        # Priority: healthy > unknown (if model loaded) > degraded (with reduced weight)
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
        
        # Last resort fallback: Use degraded predictions with reduced weight
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
        
        # Log filtering results
        if predictions and not healthy_predictions:
            filtered_out = [
                {
                    "model_name": pred.model_name,
                    "health_status": pred.health_status,
                    "reason": f"health_status='{pred.health_status}' not acceptable"
                }
                for pred in predictions
            ]
            logger.error(
                "model_predictions_all_filtered_out",
                request_id=request.request_id,
                total_predictions=len(predictions),
                healthy_predictions=len(healthy_predictions),
                filtered_predictions=filtered_out,
                message="All predictions filtered out - no acceptable predictions available"
            )
        
        # Calculate consensus using weighted average by both model performance and confidence
        # Apply weight reduction for non-healthy predictions
        if healthy_predictions:
            # Weighted average: combines model performance weight (from historical accuracy/profit)
            # with prediction confidence to get final weight for each prediction
            total_weight = 0.0
            weighted_sum = 0.0
            confidence_sum = 0.0
            
            # Log individual predictions for debugging
            prediction_details = []
            
            for pred in healthy_predictions:
                # Get model weight (based on historical performance metrics)
                # Default to equal weight if not set
                model_weight = self.model_weights.get(
                    pred.model_name, 
                    1.0 / len(healthy_predictions)
                )
                
                # Apply health status weight multiplier
                # Healthy predictions get full weight, unknown get 0.8x, degraded get 0.5x
                health_weight_multiplier = {
                    "healthy": 1.0,
                    "unknown": 0.8,
                    "degraded": 0.5
                }.get(pred.health_status, 0.5)
                
                # Combined weight = performance_weight * prediction_confidence * health_weight
                # This ensures models with better historical performance AND higher
                # confidence in current prediction AND healthy status get more weight
                combined_weight = model_weight * pred.confidence * health_weight_multiplier
                
                weighted_sum += pred.prediction * combined_weight
                total_weight += combined_weight
                confidence_sum += pred.confidence
                
                # Track for logging
                prediction_details.append({
                    "model": pred.model_name,
                    "prediction": pred.prediction,
                    "confidence": pred.confidence,
                    "model_weight": model_weight,
                    "combined_weight": combined_weight
                })
            
            if total_weight > 0:
                consensus_prediction = weighted_sum / total_weight
                # Average confidence across all predictions
                consensus_confidence = confidence_sum / len(healthy_predictions)
            else:
                # If total_weight is 0, it means all predictions have 0 confidence
                # Fall back to simple average of predictions
                if len(healthy_predictions) > 0:
                    consensus_prediction = sum(pred.prediction for pred in healthy_predictions) / len(healthy_predictions)
                    consensus_confidence = confidence_sum / len(healthy_predictions) if confidence_sum > 0 else 0.0
                else:
                    consensus_prediction = 0.0
                    consensus_confidence = 0.0
            
            # Log consensus calculation details for debugging
            logger.debug(
                "consensus_calculation",
                healthy_predictions_count=len(healthy_predictions),
                total_models=len(self.models),
                prediction_details=prediction_details,
                total_weight=total_weight,
                weighted_sum=weighted_sum,
                consensus_prediction=consensus_prediction,
                consensus_confidence=consensus_confidence
            )
        else:
            consensus_prediction = 0.0
            consensus_confidence = 0.0
            
            # Log detailed information about why consensus failed
            prediction_statuses = {}
            for pred in predictions:
                status = pred.health_status
                if status not in prediction_statuses:
                    prediction_statuses[status] = []
                prediction_statuses[status].append(pred.model_name)
            
            logger.warning(
                "consensus_calculation_no_acceptable_predictions",
                total_predictions=len(predictions),
                total_models=len(self.models),
                prediction_statuses=prediction_statuses,
                message="No acceptable predictions available for consensus calculation. "
                       "All predictions were filtered out or failed."
            )
        
        return MCPModelResponse(
            request_id=request.request_id,
            predictions=predictions,
            consensus_prediction=consensus_prediction,
            consensus_confidence=consensus_confidence,
            healthy_models=len(healthy_predictions),
            total_models=len(self.models),
            timestamp=datetime.utcnow()
        )
    
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
        # If all models are healthy, return "healthy"
        # If some models are unhealthy, return "degraded"
        # If all models are unhealthy (but models exist), return "unhealthy"
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
            # All models exist but none are healthy
            registry_health = "unhealthy"
            status = "down"
        
        return {
            "status": status,  # Standard status field for health checks ("up", "degraded", "down", "unknown")
            "total_models": len(self.models),
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

