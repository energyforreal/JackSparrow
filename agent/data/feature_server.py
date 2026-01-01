"""
MCP Feature Server.

Implements MCP Feature Protocol for standardized feature communication.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum
from pydantic import BaseModel
import uuid
import time
import structlog

from agent.data.feature_engineering import FeatureEngineering
from agent.data.market_data_service import MarketDataService
from agent.events.event_bus import event_bus
from agent.events.schemas import FeatureRequestEvent, FeatureComputedEvent, EventType

logger = structlog.get_logger()


class FeatureQuality(str, Enum):
    """Feature quality enumeration."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    DEGRADED = "degraded"


class MCPFeature(BaseModel):
    """MCP Feature Protocol structure."""
    name: str
    version: str
    value: float
    timestamp: datetime
    quality: FeatureQuality
    metadata: Dict[str, Any]
    computation_time_ms: float


class MCPFeatureRequest(BaseModel):
    """MCP Feature Protocol request."""
    feature_names: List[str]
    symbol: str
    timestamp: Optional[datetime] = None
    version: str = "latest"
    require_quality: FeatureQuality = FeatureQuality.MEDIUM


class MCPFeatureResponse(BaseModel):
    """MCP Feature Protocol response."""
    features: List[MCPFeature]
    quality_score: float
    overall_quality: FeatureQuality
    timestamp: datetime
    request_id: str


class MCPFeatureServer:
    """MCP Feature Server implementing Feature Protocol."""
    
    def __init__(self):
        """Initialize feature server."""
        self.feature_engineering = FeatureEngineering()
        self.market_data_service = MarketDataService()
        self.feature_registry: Dict[str, str] = {
            "rsi_14": "1.0.0",
            "macd_signal": "1.0.0",
            "bb_upper": "1.0.0",
            "bb_lower": "1.0.0",
            "volume_sma": "1.0.0",
            "price_sma": "1.0.0",
            "volatility": "1.0.0"
        }
        self._computing: Dict[str, bool] = {}  # Track ongoing computations
    
    async def initialize(self):
        """Initialize feature server."""
        await self.market_data_service.initialize()
        # Register event handler
        event_bus.subscribe(EventType.FEATURE_REQUEST, self._handle_feature_request_event)
    
    async def shutdown(self):
        """Shutdown feature server."""
        await self.market_data_service.shutdown()
    
    async def _handle_feature_request_event(self, event: FeatureRequestEvent):
        """Handle feature request event.
        
        Args:
            event: Feature request event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            feature_names = payload.get("feature_names", [])
            
            # Check if already computing for this symbol
            computation_key = f"{symbol}:{','.join(sorted(feature_names))}"
            if self._computing.get(computation_key, False):
                logger.debug(
                    "feature_computation_already_in_progress",
                    symbol=symbol,
                    computation_key=computation_key
                )
                return
            
            self._computing[computation_key] = True
            
            try:
                # Create MCP request
                request = MCPFeatureRequest(
                    feature_names=feature_names,
                    symbol=symbol,
                    timestamp=payload.get("timestamp"),
                    version=payload.get("version", "latest")
                )
                
                # Get features
                response = await self.get_features(request)
                
                # Emit feature computed event
                await self._emit_feature_computed_event(event, response)
                
            finally:
                self._computing[computation_key] = False
                
        except Exception as e:
            logger.error(
                "feature_request_event_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
            self._computing[computation_key] = False
    
    async def _emit_feature_computed_event(self, request_event: FeatureRequestEvent, response: MCPFeatureResponse):
        """Emit feature computed event.
        
        Args:
            request_event: Original feature request event
            response: Feature response
        """
        try:
            # Convert features to dict
            features_dict = {
                feat.name: feat.value
                for feat in response.features
            }
            
            event = FeatureComputedEvent(
                source="feature_server",
                correlation_id=request_event.event_id,
                payload={
                    "symbol": request_event.payload.get("symbol"),
                    "features": features_dict,
                    "quality_score": response.quality_score,
                    "timestamp": response.timestamp
                }
            )
            
            await event_bus.publish(event)
            
            logger.info(
                "feature_computed_event_emitted",
                symbol=request_event.payload.get("symbol"),
                feature_count=len(features_dict),
                quality_score=response.quality_score,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "feature_computed_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def get_features(self, request: MCPFeatureRequest) -> MCPFeatureResponse:
        """Get features according to MCP Feature Protocol."""
        
        request_id = str(uuid.uuid4())
        timestamp = request.timestamp or datetime.utcnow()
        
        features: List[MCPFeature] = []
        
        # Get market data
        market_data = await self.market_data_service.get_market_data(
            symbol=request.symbol,
            limit=100
        )
        
        if not market_data or not market_data.get("candles"):
            # Return degraded features if no market data
            return MCPFeatureResponse(
                features=[],
                quality_score=0.0,
                overall_quality=FeatureQuality.DEGRADED,
                timestamp=timestamp,
                request_id=request_id
            )
        
        # Compute each feature
        for feature_name in request.feature_names:
            start_time = time.time()
            
            try:
                # Compute feature
                feature_value = await self._compute_feature(
                    feature_name=feature_name,
                    symbol=request.symbol,
                    market_data=market_data
                )
                
                computation_time_ms = (time.time() - start_time) * 1000
                
                # Assess quality
                quality = self._assess_quality(feature_value, market_data)
                
                # Get version
                version = self.feature_registry.get(feature_name, "1.0.0")
                
                # Create MCP feature
                mcp_feature = MCPFeature(
                    name=feature_name,
                    version=version,
                    value=feature_value,
                    timestamp=timestamp,
                    quality=quality,
                    metadata={
                        "symbol": request.symbol,
                        "computation_method": self.feature_engineering.get_computation_method(feature_name)
                    },
                    computation_time_ms=computation_time_ms
                )
                
                features.append(mcp_feature)
                
            except Exception as e:
                # Feature computation failed
                logger.error(
                    "feature_server_compute_failed",
                    feature_name=feature_name,
                    symbol=symbol,
                    error=str(e),
                    exc_info=True
                )
                features.append(MCPFeature(
                    name=feature_name,
                    version=self.feature_registry.get(feature_name, "1.0.0"),
                    value=0.0,
                    timestamp=timestamp,
                    quality=FeatureQuality.DEGRADED,
                    metadata={"error": str(e)},
                    computation_time_ms=0.0
                ))
        
        # Calculate overall quality score
        quality_score = self._calculate_quality_score(features)
        overall_quality = self._determine_overall_quality(quality_score)
        
        # FEATURE SERVER: Log warning if quality is DEGRADED
        if overall_quality == FeatureQuality.DEGRADED:
            logger.warning("FEATURE SERVER: DEGRADED — Sending partial features")
        
        return MCPFeatureResponse(
            features=features,
            quality_score=quality_score,
            overall_quality=overall_quality,
            timestamp=datetime.utcnow(),
            request_id=request_id
        )
    
    async def _compute_feature(
        self,
        feature_name: str,
        symbol: str,
        market_data: Dict[str, Any]
    ) -> float:
        """Compute feature value."""
        
        candles = market_data.get("candles", [])
        if not candles:
            raise ValueError("No market data available")
        
        # Use feature engineering service
        return await self.feature_engineering.compute_feature(
            feature_name=feature_name,
            candles=candles
        )
    
    def _assess_quality(self, value: float, market_data: Dict[str, Any]) -> FeatureQuality:
        """Assess feature quality."""
        
        # Simple quality assessment
        if value is None or value != value:  # NaN check
            return FeatureQuality.DEGRADED
        
        # Check data freshness
        data_age = market_data.get("data_age_seconds", 0)
        if data_age > 3600:  # > 1 hour old
            return FeatureQuality.LOW
        
        if data_age > 600:  # > 10 minutes old
            return FeatureQuality.MEDIUM
        
        # Check value validity
        if abs(value) > 1000000:  # Unreasonable value
            return FeatureQuality.DEGRADED
        
        return FeatureQuality.HIGH
    
    def _calculate_quality_score(self, features: List[MCPFeature]) -> float:
        """Calculate overall quality score (0.0 to 1.0)."""
        
        if not features:
            return 0.0
        
        quality_weights = {
            FeatureQuality.HIGH: 1.0,
            FeatureQuality.MEDIUM: 0.7,
            FeatureQuality.LOW: 0.4,
            FeatureQuality.DEGRADED: 0.1
        }
        
        total_score = sum(quality_weights.get(f.quality, 0.0) for f in features)
        return total_score / len(features)
    
    def _determine_overall_quality(self, quality_score: float) -> FeatureQuality:
        """Determine overall quality from score."""
        
        if quality_score >= 0.9:
            return FeatureQuality.HIGH
        elif quality_score >= 0.7:
            return FeatureQuality.MEDIUM
        elif quality_score >= 0.4:
            return FeatureQuality.LOW
        else:
            return FeatureQuality.DEGRADED
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        
        market_data_health = await self.market_data_service.get_health_status()
        
        return {
            "status": "up" if market_data_health.get("status") == "up" else "down",
            "feature_registry_count": len(self.feature_registry),
            "market_data_service": market_data_health
        }

