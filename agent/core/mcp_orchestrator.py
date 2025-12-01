"""
MCP Orchestrator.

Coordinates all MCP components (Feature, Model, Reasoning protocols).
Provides unified interface for agent core.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid

from agent.data.feature_server import MCPFeatureServer, MCPFeatureRequest, MCPFeatureResponse
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelRequest, MCPModelResponse
from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest, MCPReasoningChain
from decimal import Decimal


class MCPOrchestrator:
    """MCP Orchestrator coordinating all MCP components."""
    
    def __init__(self):
        """Initialize MCP orchestrator."""
        self.feature_server = MCPFeatureServer()
        self.model_registry = MCPModelRegistry()
        self.reasoning_engine = MCPReasoningEngine(
            feature_server=self.feature_server,
            model_registry=self.model_registry
        )
    
    async def initialize(self):
        """Initialize all MCP components."""
        await self.feature_server.initialize()
        await self.model_registry.initialize()
        await self.reasoning_engine.initialize()
    
    async def shutdown(self):
        """Shutdown all MCP components."""
        await self.reasoning_engine.shutdown()
        await self.model_registry.shutdown()
        await self.feature_server.shutdown()
    
    # Feature Protocol Interface
    
    async def get_features(
        self,
        feature_names: List[str],
        symbol: str,
        timestamp: Optional[datetime] = None,
        version: str = "latest"
    ) -> MCPFeatureResponse:
        """Get features via MCP Feature Protocol."""
        
        request = MCPFeatureRequest(
            feature_names=feature_names,
            symbol=symbol,
            timestamp=timestamp or datetime.utcnow(),
            version=version
        )
        
        return await self.feature_server.get_features(request)
    
    # Model Protocol Interface
    
    async def get_predictions(
        self,
        features: List[float],
        context: Dict[str, Any],
        require_explanation: bool = True
    ) -> MCPModelResponse:
        """Get predictions from all models via MCP Model Protocol."""
        
        request = MCPModelRequest(
            request_id=str(uuid.uuid4()),
            features=features,
            context=context,
            require_explanation=require_explanation
        )
        
        return await self.model_registry.get_predictions(request)
    
    # Reasoning Protocol Interface
    
    async def generate_reasoning(
        self,
        symbol: str,
        market_context: Dict[str, Any],
        use_memory: bool = True
    ) -> MCPReasoningChain:
        """Generate reasoning chain via MCP Reasoning Protocol."""
        
        request = MCPReasoningRequest(
            symbol=symbol,
            market_context=market_context,
            use_memory=use_memory
        )
        
        return await self.reasoning_engine.generate_reasoning(request)
    
    # Combined Workflow
    
    async def get_trading_decision(
        self,
        symbol: str,
        market_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get complete trading decision using all MCP protocols."""
        
        # Step 1: Get features - Request all 50 features required by ML models
        # This matches the FEATURE_LIST from training scripts
        feature_names = [
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
        
        feature_response = await self.get_features(
            feature_names=feature_names,
            symbol=symbol
        )
        
        # Step 2: Get model predictions
        features_dict = {
            feat.name: feat.value
            for feat in feature_response.features
        }
        
        context = market_context or {}
        context["features"] = features_dict
        context["symbol"] = symbol
        context["feature_names"] = list(features_dict.keys())
        
        model_response = await self.get_predictions(
            features=list(features_dict.values()),
            context=context,
            require_explanation=True
        )
        
        # Step 3: Generate reasoning chain
        reasoning_chain = await self.generate_reasoning(
            symbol=symbol,
            market_context=context,
            use_memory=True
        )
        
        # Step 4: Synthesize decision
        decision = self._synthesize_decision(
            feature_response=feature_response,
            model_response=model_response,
            reasoning_chain=reasoning_chain
        )
        
        return decision
    
    def _synthesize_decision(
        self,
        feature_response: MCPFeatureResponse,
        model_response: MCPModelResponse,
        reasoning_chain: MCPReasoningChain
    ) -> Dict[str, Any]:
        """Synthesize final trading decision from all MCP components."""
        
        # Use consensus_prediction from model registry (already calculated with proper weights)
        # The registry calculates consensus using only healthy models with proper weights
        predictions = model_response.predictions
        healthy_predictions = [
            pred for pred in predictions
            if pred.health_status == "healthy"
        ]
        
        # Use consensus_prediction from model_response (already calculated correctly)
        consensus_prediction = model_response.consensus_prediction
        
        # Log individual predictions for debugging
        import structlog
        logger = structlog.get_logger()
        if healthy_predictions:
            logger.debug(
                "consensus_calculation_details",
                total_predictions=len(predictions),
                healthy_predictions=len(healthy_predictions),
                individual_predictions=[
                    {
                        "model": pred.model_name,
                        "prediction": pred.prediction,
                        "confidence": pred.confidence,
                        "health": pred.health_status
                    }
                    for pred in healthy_predictions
                ],
                consensus_prediction=consensus_prediction,
                consensus_confidence=model_response.consensus_confidence
            )
        
        # Convert consensus prediction (-1.0 to +1.0) to signal string
        if not healthy_predictions:
            signal = "HOLD"
            confidence = 0.0
            weighted_signal = 0.0
        else:
            weighted_signal = consensus_prediction
            
            # Convert to signal
            if weighted_signal >= 0.7:
                signal = "STRONG_BUY"
            elif weighted_signal >= 0.3:
                signal = "BUY"
            elif weighted_signal <= -0.7:
                signal = "STRONG_SELL"
            elif weighted_signal <= -0.3:
                signal = "SELL"
            else:
                signal = "HOLD"
            
            # Use consensus_confidence from model_response or reasoning chain confidence
            confidence = model_response.consensus_confidence if model_response.consensus_confidence > 0 else reasoning_chain.final_confidence
        
        # Calculate position size based on consensus signal strength
        position_size = min(abs(weighted_signal) * 0.1, 0.1) if healthy_predictions else 0.0
        
        return {
            "signal": signal,
            "confidence": confidence,
            "position_size": position_size,
            "reasoning_chain": reasoning_chain.dict(),
            "model_predictions": [pred.dict() for pred in predictions],
            "feature_quality": feature_response.quality_score,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all MCP components."""
        
        feature_health = await self.feature_server.get_health_status()
        model_health = await self.model_registry.get_health_status()
        reasoning_health = await self.reasoning_engine.get_health_status()
        
        return {
            "feature_server": feature_health,
            "model_registry": model_health,
            "reasoning_engine": reasoning_health,
            "overall_status": "healthy" if all(
                h.get("status") == "up" for h in [feature_health, model_health, reasoning_health]
            ) else "degraded"
        }


# Global MCP orchestrator instance
mcp_orchestrator = MCPOrchestrator()

