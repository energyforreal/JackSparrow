"""
MCP Orchestrator - Core coordinator for all MCP components.

Coordinates the interaction between MCP Feature Server, MCP Model Registry,
and MCP Reasoning Engine to provide unified AI agent functionality.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import asyncio
import structlog

from agent.data.feature_server import MCPFeatureServer, MCPFeatureRequest, MCPFeatureResponse
from agent.models.mcp_model_registry import (
    MCPModelRegistry,
    MCPModelRequest,
    MCPModelResponse,
    NoModelsRegisteredError,
    NoHealthyModelPredictionsError,
)
from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest, MCPReasoningChain
from agent.memory.vector_store import VectorMemoryStore, DecisionContext
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    ModelPredictionRequestEvent,
    ModelPredictionCompleteEvent,
    ReasoningRequestEvent,
    ReasoningCompleteEvent,
    DecisionReadyEvent,
    EventType
)
from agent.core.config import settings

logger = structlog.get_logger()


class MCPOrchestrator:
    """Main MCP Orchestrator coordinating all MCP components."""
    
    def __init__(self):
        """Initialize MCP Orchestrator."""
        self.feature_server: Optional[MCPFeatureServer] = None
        self.model_registry: Optional[MCPModelRegistry] = None
        self.reasoning_engine: Optional[MCPReasoningEngine] = None
        self.vector_store: Optional[VectorMemoryStore] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize all MCP components."""
        try:
            logger.info("mcp_orchestrator_initializing", message="Starting MCP Orchestrator initialization")

            # Initialize MCP Feature Server
            self.feature_server = MCPFeatureServer()
            await self.feature_server.initialize()
            logger.info("mcp_orchestrator_feature_server_initialized")

            # Initialize MCP Model Registry
            self.model_registry = MCPModelRegistry()
            await self.model_registry.initialize()

            # Discover and load models
            from agent.models.model_discovery import ModelDiscovery
            discovery = ModelDiscovery(self.model_registry)
            discovered_models = await discovery.discover_models()
            logger.info("mcp_orchestrator_models_discovered",
                       model_count=len(discovered_models),
                       registry_models=len(self.model_registry.models))

            # Enforce that at least one ML model is available before continuing.
            if not self.model_registry.models:
                logger.critical(
                    "mcp_orchestrator_no_models_loaded",
                    discovered_count=len(discovered_models),
                    message="No ML models were loaded during initialization. Agent cannot run without models.",
                )
                raise RuntimeError(
                    "MCP Orchestrator initialization failed: no ML models loaded."
                )

            logger.info("mcp_orchestrator_model_registry_initialized")

            # Initialize Vector Memory Store for historical context retrieval (Step 2)
            self.vector_store = VectorMemoryStore(
                max_memory_size=10000,
                similarity_threshold=0.5)
            await self.vector_store.initialize()

            # Initialize MCP Reasoning Engine
            self.reasoning_engine = MCPReasoningEngine(
                feature_server=self.feature_server,
                model_registry=self.model_registry,
                vector_store=self.vector_store
            )
            await self.reasoning_engine.initialize()
            logger.info("mcp_orchestrator_reasoning_engine_initialized")

            # Register event handlers
            event_bus.subscribe(EventType.MODEL_PREDICTION_REQUEST, self._handle_prediction_request)
            event_bus.subscribe(EventType.REASONING_REQUEST, self._handle_reasoning_request)

            self._initialized = True
            logger.info("mcp_orchestrator_initialization_complete",
                       message="MCP Orchestrator fully initialized and ready")

        except Exception as e:
            logger.error("mcp_orchestrator_initialization_failed",
                        error=str(e),
                        exc_info=True)
            raise
    
    async def shutdown(self):
        """Shutdown all MCP components."""
        try:
            logger.info("mcp_orchestrator_shutdown_starting")

            if self.reasoning_engine:
                await self.reasoning_engine.shutdown()

            if self.vector_store:
                await self.vector_store.shutdown()
                self.vector_store = None

            if self.model_registry:
                await self.model_registry.shutdown()

            if self.feature_server:
                await self.feature_server.shutdown()
    
            logger.info("mcp_orchestrator_shutdown_complete")

        except Exception as e:
            logger.error("mcp_orchestrator_shutdown_failed", error=str(e), exc_info=True)
    
    async def process_prediction_request(
        self,
        symbol: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a complete prediction request through all MCP components.

        This is the main entry point for AI predictions, coordinating:
        1. Feature computation via MCP Feature Server
        2. Model inference via MCP Model Registry
        3. Reasoning synthesis via MCP Reasoning Engine

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            context: Additional context for prediction

        Returns:
            Complete prediction result with reasoning chain
        """
        if not self._initialized:
            raise RuntimeError("MCP Orchestrator not initialized")

        try:
            logger.info("mcp_orchestrator_prediction_start",
                       symbol=symbol,
                       context_keys=list(context.keys()) if context else None)

            context = context or {}

            # Step 1: Get features via MCP Feature Server
            feature_request = MCPFeatureRequest(
                feature_names=self._get_required_features(),
            symbol=symbol,
                timestamp=context.get("timestamp"),
                require_quality=context.get("feature_quality", "medium")
            )

            logger.debug("mcp_orchestrator_requesting_features",
                        symbol=symbol,
                        feature_count=len(feature_request.feature_names))

            feature_response = await self.feature_server.get_features(feature_request)

            if not feature_response.features:
                logger.warning("mcp_orchestrator_no_features_available",
                             symbol=symbol,
                             message="No features available for prediction")
                # Try to get at least basic features before giving up
                # This might happen if feature server is still initializing
                try:
                    # Request basic required features explicitly
                    basic_features = self._get_required_features()
                    basic_feature_response = await self.get_features(basic_features, symbol)
                    if basic_feature_response.features:
                        feature_response = basic_feature_response
                        logger.info("mcp_orchestrator_basic_features_retrieved",
                                  symbol=symbol,
                                  feature_count=len(basic_feature_response.features))
                    else:
                        return self._create_empty_prediction_response(symbol, context)
                except Exception as e:
                    logger.warning("mcp_orchestrator_basic_features_failed",
                                 symbol=symbol,
                                 error=str(e))
                    return self._create_empty_prediction_response(symbol, context)

            # Step 2: Prepare model context with features
            model_context = {
                **context,
                "features": [feature.value for feature in feature_response.features],
                "feature_names": [feature.name for feature in feature_response.features],
                "feature_quality": feature_response.overall_quality.value,
                "current_price": context.get("current_price")  # For regressor normalization
            }

            # Step 3: Get model predictions via MCP Model Registry
            model_request = MCPModelRequest(
                request_id=f"pred_{symbol}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                features=[feature.value for feature in feature_response.features],  # Raw feature values
                context=model_context,
                require_explanation=True
            )

            logger.debug("mcp_orchestrator_requesting_predictions",
                        symbol=symbol,
                        model_request_id=model_request.request_id)

            try:
                model_response = await self.model_registry.get_predictions(model_request)
            except NoModelsRegisteredError as e:
                logger.error(
                    "mcp_orchestrator_no_models_registered",
                    symbol=symbol,
                    error=str(e),
                    message="Prediction request failed because no ML models are registered.",
                )
                return self._create_model_error_prediction_response(
                    symbol=symbol,
                    context=context,
                    error_code="NO_MODELS_REGISTERED",
                    error_message=str(e),
                )
            except NoHealthyModelPredictionsError as e:
                logger.error(
                    "mcp_orchestrator_no_model_predictions",
                    symbol=symbol,
                    error=str(e),
                    message="Prediction request failed because no acceptable model predictions are available.",
                )
                return self._create_model_error_prediction_response(
                    symbol=symbol,
                    context=context,
                    error_code="NO_MODEL_PREDICTIONS",
                    error_message=str(e),
                )

            # Step 4: Generate reasoning chain via MCP Reasoning Engine
            # Build a rich market_context that can also be forwarded to
            # downstream consumers (backend / frontend) for transparency.
            # Start from raw feature values.
            features_dict: Dict[str, Any] = {
                f.name: f.value for f in feature_response.features
            }
            # Derive a generic volatility field when possible so the reasoning
            # engine's risk assessment step can operate even if only
            # volatility_10/volatility_20 are present.
            if "volatility" not in features_dict:
                derived_volatility = None
                if "volatility_10" in features_dict:
                    derived_volatility = features_dict["volatility_10"]
                elif "volatility_20" in features_dict:
                    derived_volatility = features_dict["volatility_20"]
                if derived_volatility is not None:
                    features_dict["volatility"] = derived_volatility

            market_context_for_reasoning: Dict[str, Any] = {
                **(context or {}),
                "features": features_dict,
                "model_predictions": [
                    {
                        "model_name": pred.model_name,
                        "model_version": pred.model_version,
                        "prediction": pred.prediction,
                        "confidence": pred.confidence,
                        "reasoning": pred.reasoning,
                        "features_used": getattr(pred, "features_used", []),
                        "feature_importance": getattr(pred, "feature_importance", {}),
                        "health_status": getattr(pred, "health_status", "healthy"),
                        "model_type": getattr(pred, "model_type", "unknown"),
                    }
                    for pred in model_response.predictions
                ],
                "consensus_signal": model_response.consensus_prediction,
                "consensus_confidence": model_response.consensus_confidence,
                # Keep both the qualitative and quantitative quality scores so
                # the reasoning engine and API consumers can use either.
                "feature_quality": feature_response.overall_quality.value,
                "quality_score": feature_response.quality_score,
            }

            reasoning_request = MCPReasoningRequest(
                symbol=symbol,
                market_context=market_context_for_reasoning,
                use_memory=False,  # TODO: Enable when VectorMemoryStore is implemented
            )

            reasoning_chain = await self.reasoning_engine.generate_reasoning(reasoning_request)

            # Step 5: Compile complete response
            result = {
                "symbol": symbol,
                "timestamp": datetime.utcnow(),
                "features": {
                    "data": [{"name": f.name, "value": f.value, "quality": f.quality.value}
                           for f in feature_response.features],
                    "quality_score": feature_response.quality_score,
                    "overall_quality": feature_response.overall_quality.value,
                    "count": len(feature_response.features)
                },
                "models": {
                    "predictions": [
                        {
                            "model_name": pred.model_name,
                            "model_version": pred.model_version,
                            "prediction": pred.prediction,
                            "confidence": pred.confidence,
                            "reasoning": pred.reasoning,
                            "features_used": pred.features_used,
                            "feature_importance": pred.feature_importance,
                            "computation_time_ms": pred.computation_time_ms,
                            "health_status": pred.health_status
                        }
                        for pred in model_response.predictions
                    ],
                    "consensus_prediction": model_response.consensus_prediction,
                    "consensus_confidence": model_response.consensus_confidence,
                    "healthy_models": model_response.healthy_models,
                    "total_models": model_response.total_models,
                },
                # Expose model_predictions and market_context at the top level
                # so HTTP and event consumers can access them directly without
                # re-deriving from nested structures.
                "model_predictions": [
                    {
                        "model_name": pred.model_name,
                        "model_version": pred.model_version,
                        "prediction": pred.prediction,
                        "confidence": pred.confidence,
                        "reasoning": pred.reasoning,
                        "features_used": pred.features_used,
                        "feature_importance": pred.feature_importance,
                        "computation_time_ms": pred.computation_time_ms,
                        "health_status": pred.health_status,
                    }
                    for pred in model_response.predictions
                ],
                "market_context": market_context_for_reasoning,
                "reasoning": {
                    "chain_id": reasoning_chain.chain_id,
                    "steps": [
                        {
                            "step_number": step.step_number,
                            "step_name": step.step_name,
                            "description": step.description,
                            "evidence": step.evidence,
                            "confidence": step.confidence,
                            "timestamp": step.timestamp.isoformat()
                        }
                        for step in reasoning_chain.steps
                    ],
                    "conclusion": reasoning_chain.conclusion,
                    "final_confidence": reasoning_chain.final_confidence
                },
                "decision": self._extract_decision_from_reasoning(reasoning_chain)
            }

            logger.info("mcp_orchestrator_prediction_complete",
                       symbol=symbol,
                       consensus_prediction=model_response.consensus_prediction,
                       final_confidence=reasoning_chain.final_confidence,
                       decision=result["decision"]["signal"])

            return result

        except Exception as e:
            logger.error("mcp_orchestrator_prediction_failed",
                        symbol=symbol,
                        error=str(e),
                        exc_info=True)
            return self._create_error_prediction_response(symbol, context, str(e))

    async def get_features(
        self,
        feature_names: List[str],
        symbol: str,
        timestamp: Optional[datetime] = None
    ) -> MCPFeatureResponse:
        """
        Get features via MCP Feature Protocol.

        This is a wrapper method that delegates to the feature server.

        Args:
            feature_names: List of feature names to compute
            symbol: Trading symbol (e.g., "BTCUSD")
            timestamp: Optional timestamp for historical data

        Returns:
            MCPFeatureResponse with computed features
        """
        if not self._initialized:
            raise RuntimeError("MCP Orchestrator not initialized")

        if not self.feature_server:
            raise RuntimeError("Feature server not initialized")

        request = MCPFeatureRequest(
            feature_names=feature_names,
            symbol=symbol,
            timestamp=timestamp,
            require_quality="medium"
        )

        logger.debug("mcp_orchestrator_getting_features",
                    symbol=symbol,
                    feature_count=len(feature_names))

        return await self.feature_server.get_features(request)

    async def get_trading_decision(
        self,
        symbol: str,
        market_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get trading decision with signal, confidence, and reasoning.

        This is a simplified interface that returns the core decision components
        extracted from the full prediction result.

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            market_context: Market context for decision making

        Returns:
            Dict with signal, confidence, position_size, and reasoning_chain
        """
        result = await self.process_prediction_request(symbol, market_context)

        # Extract the decision components that the agent expects
        decision = result.get("decision", {})
        reasoning = result.get("reasoning", {})

        return {
            "signal": decision.get("signal"),
            "confidence": reasoning.get("final_confidence"),
            "position_size": decision.get("position_size", 0.0),
            "reasoning_chain": {
                "chain_id": reasoning.get("chain_id"),
                "steps": reasoning.get("steps", []),
                "conclusion": reasoning.get("conclusion"),
                "final_confidence": reasoning.get("final_confidence")
            },
            "timestamp": result.get("timestamp")
        }

    async def generate_reasoning(
        self,
        symbol: str,
        market_context: Optional[Dict[str, Any]] = None,
        use_memory: bool = False
    ) -> MCPReasoningChain:
        """
        Generate reasoning chain for trading decision.

        This is a wrapper method that delegates to the reasoning engine.

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            market_context: Market context for reasoning
            use_memory: Whether to use memory for context

        Returns:
            MCPReasoningChain with 6-step reasoning process
        """
        if not self._initialized:
            raise RuntimeError("MCP Orchestrator not initialized")

        if not self.reasoning_engine:
            raise RuntimeError("Reasoning engine not initialized")

        request = MCPReasoningRequest(
            symbol=symbol,
            market_context=market_context or {},
            use_memory=use_memory
        )

        logger.debug("mcp_orchestrator_generating_reasoning",
                    symbol=symbol,
                    use_memory=use_memory)

        return await self.reasoning_engine.generate_reasoning(request)

    def _get_required_features(self) -> List[str]:
        """Get list of required features for ML models."""
        # This should match the FEATURE_LIST from training scripts
        return [
            # Price-based (16 features)
            'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
            'ema_12', 'ema_26', 'ema_50',
            'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
            'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
            # Momentum (10 features)
            'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
            'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
            'momentum_10', 'momentum_20',
            # Trend (8 features)
            'macd', 'macd_signal', 'macd_histogram',
            'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
            'trend_strength',
            # Volatility (8 features)
            'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
            'atr_14', 'atr_20',
            'volatility_10', 'volatility_20',
            # Volume (6 features)
            'volume_sma_20', 'volume_ratio', 'obv',
            'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
            # Returns (2 features)
            'returns_1h', 'returns_24h'
        ]
        
    def _extract_decision_from_reasoning(self, reasoning_chain: MCPReasoningChain) -> Dict[str, Any]:
        """Extract trading decision from reasoning chain conclusion."""
        conclusion = reasoning_chain.conclusion.lower()

        if "strong_buy" in conclusion:
            signal = "STRONG_BUY"
            position_size = 0.1  # 10% of portfolio
        elif "buy" in conclusion:
            signal = "BUY"
            position_size = 0.05  # 5% of portfolio
        elif "strong_sell" in conclusion:
            signal = "STRONG_SELL"
            position_size = 0.1  # 10% of portfolio
        elif "sell" in conclusion:
            signal = "SELL"
            position_size = 0.05  # 5% of portfolio
        else:
            signal = "HOLD"
            position_size = 0.0
        
        return {
            "signal": signal,
            "position_size": position_size,
            "confidence": reasoning_chain.final_confidence,
            "reasoning": reasoning_chain.conclusion
        }

    def _create_empty_prediction_response(self, symbol: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Create explicit error response when no features are available.

        This intentionally does NOT fabricate a neutral HOLD decision. Instead it
        returns an error payload that callers must treat as \"no decision\".
        """
        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow(),
            "success": False,
            "error_code": "NO_FEATURES",
            "error": "No features available for prediction",
            "features": {"count": 0, "quality_score": 0.0},
            "models": {
                "predictions": [],
                "consensus_prediction": 0.0,
                "healthy_models": 0,
                "total_models": 0,
            },
            "reasoning": {
                "conclusion": "Insufficient data for ML-based decision",
                "final_confidence": 0.0,
            },
        }

    def _create_model_error_prediction_response(
        self,
        symbol: str,
        context: Dict[str, Any],
        error_code: str,
        error_message: str,
    ) -> Dict[str, Any]:
        """Create explicit error response when models cannot provide predictions."""
        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow(),
            "success": False,
            "error_code": error_code,
            "error": error_message,
            "context": context or {},
            "features": context.get("features") if isinstance(context, dict) else None,
            "models": {
                "predictions": [],
                "consensus_prediction": 0.0,
                "healthy_models": 0,
                "total_models": len(self.model_registry.models)
                if self.model_registry
                else 0,
            },
        }
        
    def _create_error_prediction_response(self, symbol: str, context: Dict[str, Any], error: str) -> Dict[str, Any]:
        """Create error prediction response."""
        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow(),
            "error": error,
            "features": {"count": 0, "quality_score": 0.0},
            "models": {"predictions": [], "consensus_prediction": 0.0, "healthy_models": 0, "total_models": 0},
            "reasoning": {"conclusion": f"HOLD - Error: {error}", "final_confidence": 0.0},
            "decision": {"signal": "HOLD", "position_size": 0.0, "confidence": 0.0},
        }

    # ------------------------------------------------------------------
    # Helpers for per-model reasoning used by downstream consumers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_signal_from_prediction(prediction: float) -> str:
        """
        Map a continuous prediction in [-1, 1] to a discrete signal.

        This is intentionally simple and is only used when an explicit
        per-model signal is not already provided by the model output.
        """
        try:
            value = float(prediction)
        except (TypeError, ValueError):
            return "HOLD"

        if value > 0.3:
            return "BUY"
        if value < -0.3:
            return "SELL"
        return "HOLD"

    def _build_model_predictions_for_reasoning(
        self, raw_predictions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize model prediction payloads for reasoning / WebSocket consumers.

        Ensures each entry includes:
        - model_name
        - reasoning
        - confidence (float 0-1 or 0-100, left as-is; downstream callers may rescale)
        - prediction (float)
        - signal (derived from prediction when missing)
        """
        normalized: List[Dict[str, Any]] = []

        for pred in raw_predictions or []:
            if not isinstance(pred, dict):
                continue

            model_name = pred.get("model_name", "Unknown")
            reasoning = pred.get("reasoning", "")
            confidence = pred.get("confidence", 0.0)
            prediction_value = pred.get("prediction", 0.0)
            signal = pred.get("signal") or self._derive_signal_from_prediction(prediction_value)

            normalized.append(
                {
                    "model_name": model_name,
                    "reasoning": reasoning,
                    "confidence": confidence,
                    "prediction": prediction_value,
                    "signal": signal,
                }
            )

        return normalized

    def _build_decision_context_for_storage(
        self,
        symbol: str,
        decision: Dict[str, Any],
        market_context: Dict[str, Any],
        chain_id: str,
        timestamp: datetime,
    ) -> Optional[DecisionContext]:
        """
        Build a DecisionContext for storage in the vector store.

        Returns None if market_context or features are invalid.
        """
        if not self.vector_store:
            return None

        raw_features = market_context.get("features", {})
        if not isinstance(raw_features, dict):
            return None

        # Convert feature values to float for embedding computation
        features: Dict[str, float] = {}
        for k, v in raw_features.items():
            try:
                features[k] = float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                continue

        context_id = f"decision-{chain_id}-{timestamp.timestamp():.0f}"
        return DecisionContext(
            context_id=context_id,
            symbol=symbol,
            timestamp=timestamp,
            features=features,
            market_context=market_context,
            decision={
                "signal": decision.get("signal"),
                "confidence": decision.get("confidence"),
                "position_size": decision.get("position_size"),
            },
        )

    async def _store_decision_context(
        self,
        symbol: str,
        decision: Dict[str, Any],
        market_context: Dict[str, Any],
        chain_id: str,
        timestamp: datetime,
    ) -> None:
        """Store a decision context in the vector store for future similarity search."""
        if not self.vector_store:
            return
        try:
            ctx = self._build_decision_context_for_storage(
                symbol=symbol,
                decision=decision,
                market_context=market_context,
                chain_id=chain_id,
                timestamp=timestamp,
            )
            if ctx:
                await self.vector_store.store_decision_context(ctx)
                logger.debug(
                    "mcp_orchestrator_decision_context_stored",
                    context_id=ctx.context_id,
                    symbol=symbol,
                )
        except Exception as e:
            logger.warning(
                "mcp_orchestrator_decision_context_store_failed",
                symbol=symbol,
                error=str(e),
            )

    async def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of all MCP components."""
        health_status = {
            "mcp_orchestrator": {
                "status": "healthy" if self._initialized else "unhealthy",
                "initialized": self._initialized,
                "components": {}
            }
        }

        try:
            if self.feature_server:
                feature_health = await asyncio.wait_for(
                    self.feature_server.get_health_status(),
                    timeout=1.0  # 1 second timeout per component
                )
                # Ensure we have a status field
                if "status" not in feature_health:
                    feature_health["status"] = "up" if feature_health.get("feature_registry_count", 0) > 0 else "unknown"
                health_status["mcp_orchestrator"]["components"]["feature_server"] = feature_health
            else:
                health_status["mcp_orchestrator"]["components"]["feature_server"] = {"status": "unknown", "error": "Feature server not initialized"}
        except asyncio.TimeoutError:
            logger.warning("feature_server_health_timeout")
            health_status["mcp_orchestrator"]["components"]["feature_server"] = {"status": "unknown", "error": "Health check timeout"}
        except Exception as e:
            logger.error("feature_server_health_failed", error=str(e), exc_info=True)
            health_status["mcp_orchestrator"]["components"]["feature_server"] = {"status": "unknown", "error": str(e)}

        try:
            if self.model_registry:
                model_health = await asyncio.wait_for(
                    self.model_registry.get_health_status(),
                    timeout=1.0  # 1 second timeout per component
                )
                # Ensure we have required fields
                if "status" not in model_health:
                    total_models = model_health.get("total_models", 0)
                    healthy_models = model_health.get("healthy_models", 0)
                    model_health["status"] = "up" if total_models > 0 and healthy_models > 0 else "unknown"
                health_status["mcp_orchestrator"]["components"]["model_registry"] = model_health
            else:
                health_status["mcp_orchestrator"]["components"]["model_registry"] = {"status": "unknown", "error": "Model registry not initialized"}
        except asyncio.TimeoutError:
            logger.warning("model_registry_health_timeout")
            health_status["mcp_orchestrator"]["components"]["model_registry"] = {"status": "unknown", "error": "Health check timeout"}
        except Exception as e:
            logger.error("model_registry_health_failed", error=str(e), exc_info=True)
            health_status["mcp_orchestrator"]["components"]["model_registry"] = {"status": "unknown", "error": str(e)}

        try:
            if self.reasoning_engine:
                reasoning_health = await asyncio.wait_for(
                    self.reasoning_engine.get_health_status(),
                    timeout=1.0  # 1 second timeout per component
                )
                # Ensure we have a status field
                if "status" not in reasoning_health:
                    reasoning_health["status"] = "up"
                health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = reasoning_health
            else:
                health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = {"status": "unknown", "error": "Reasoning engine not initialized"}
        except asyncio.TimeoutError:
            logger.warning("reasoning_engine_health_timeout")
            health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = {"status": "unknown", "error": "Health check timeout"}
        except Exception as e:
            logger.error("reasoning_engine_health_failed", error=str(e), exc_info=True)
            health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = {"status": "unknown", "error": str(e)}

        return health_status

    async def _handle_prediction_request(self, event: ModelPredictionRequestEvent):
        """Handle prediction request event."""
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            context = payload.get("context", {})

            result = await self.process_prediction_request(symbol, context)

            # Emit completion event
            completion_event = ModelPredictionCompleteEvent(
                source="mcp_orchestrator",
                correlation_id=event.event_id,
                payload=result
            )
            await event_bus.publish(completion_event)

            # When a full decision is available from process_prediction_request,
            # emit a DecisionReadyEvent directly so downstream consumers
            # (backend/websocket/front-end) receive signals even if intermediate
            # handlers are misaligned with the payload structure.
            decision = result.get("decision") or {}
            if isinstance(decision, dict) and decision.get("signal") is not None:
                reasoning = result.get("reasoning") or {}
                decision_symbol = result.get("symbol") or symbol
                signal = decision.get("signal")
                position_size = decision.get("position_size", 0.0)
                confidence = decision.get("confidence", reasoning.get("final_confidence", 0.0))
                timestamp = result.get("timestamp") or datetime.utcnow()

                # Normalize per-model predictions so backend and frontend can
                # consistently build model_consensus and reasoning views.
                raw_model_predictions = result.get("model_predictions") or result.get("models", {}).get(
                    "predictions", []
                )
                model_predictions_for_reasoning = self._build_model_predictions_for_reasoning(
                    raw_model_predictions
                )

                reasoning_chain_payload: Dict[str, Any] = {
                    "chain_id": reasoning.get("chain_id"),
                    "steps": reasoning.get("steps", []),
                    "conclusion": reasoning.get("conclusion"),
                    "final_confidence": reasoning.get("final_confidence"),
                    "model_predictions": model_predictions_for_reasoning,
                    "market_context": result.get("market_context") or {},
                }

                decision_event = DecisionReadyEvent(
                    source="mcp_orchestrator",
                    correlation_id=event.event_id,
                    payload={
                        "symbol": decision_symbol,
                        "signal": signal,
                        "confidence": confidence,
                        "position_size": position_size,
                        "reasoning_chain": reasoning_chain_payload,
                        "timestamp": timestamp,
                    },
                )

                await event_bus.publish(decision_event)

                # Store decision context for future historical similarity search (Step 2)
                await self._store_decision_context(
                    symbol=decision_symbol,
                    decision={"signal": signal, "confidence": confidence, "position_size": position_size},
                    market_context=reasoning_chain_payload.get("market_context", {}),
                    chain_id=reasoning.get("chain_id", "unknown"),
                    timestamp=timestamp,
                )

                logger.info(
                    "mcp_orchestrator_decision_ready_emitted",
                    symbol=decision_symbol,
                    signal=signal,
                    confidence=confidence,
                    position_size=position_size,
                    event_id=decision_event.event_id,
                    correlation_id=event.event_id,
                )

        except Exception as e:
            logger.error("mcp_orchestrator_prediction_request_failed",
                        event_id=event.event_id,
                        error=str(e),
                        exc_info=True)

    async def _handle_reasoning_request(self, event):
        """Handle reasoning request event."""
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            market_context = payload.get("market_context", {})

            request = MCPReasoningRequest(
                symbol=symbol,
                market_context=market_context,
                use_memory=False  # TODO: Enable when VectorMemoryStore implemented
            )

            reasoning_chain = await self.reasoning_engine.generate_reasoning(request)

            # Normalize per-model predictions so downstream consumers can build
            # model-level views from the reasoning payload alone.
            raw_model_predictions = getattr(reasoning_chain, "model_predictions", None) or market_context.get(
                "model_predictions", []
            )
            model_predictions_for_reasoning = self._build_model_predictions_for_reasoning(
                raw_model_predictions
            )

            reasoning_chain_payload: Dict[str, Any] = {
                "chain_id": reasoning_chain.chain_id,
                "steps": [step.model_dump() for step in reasoning_chain.steps],
                "conclusion": reasoning_chain.conclusion,
                "final_confidence": reasoning_chain.final_confidence,
                "model_predictions": model_predictions_for_reasoning,
                "market_context": market_context or getattr(reasoning_chain, "market_context", {}) or {},
            }

            # Emit completion event
            completion_event = ReasoningCompleteEvent(
                source="mcp_orchestrator",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "reasoning_chain": reasoning_chain_payload,
                },
            )
            await event_bus.publish(completion_event)

            # Emit decision ready event
            decision = self._extract_decision_from_reasoning(reasoning_chain)
            decision_event = DecisionReadyEvent(
                source="mcp_orchestrator",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "signal": decision["signal"],
                    "confidence": decision["confidence"],
                    "position_size": decision["position_size"],
                    "reasoning_chain": reasoning_chain_payload,
                },
            )
            await event_bus.publish(decision_event)

            # Store decision context for future historical similarity search (Step 2)
            await self._store_decision_context(
                symbol=symbol,
                decision=decision,
                market_context=reasoning_chain_payload.get("market_context", {}),
                chain_id=reasoning_chain.chain_id,
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error("mcp_orchestrator_reasoning_request_failed",
                        event_id=event.event_id,
                        error=str(e),
                        exc_info=True)


# Create global MCP orchestrator instance
mcp_orchestrator = MCPOrchestrator()