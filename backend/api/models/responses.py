"""
Pydantic response models for API endpoints.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class HealthServiceStatus(BaseModel):
    """Health status for a single service."""
    
    status: str = Field(
        ...,
        description="Service status (up/down/degraded)",
        example="up"
    )
    latency_ms: Optional[float] = Field(
        default=None,
        description="Service latency in milliseconds",
        example=5.2
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if service is down",
        example=None
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional service details"
    )


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str = Field(
        ...,
        description="Overall system status",
        example="healthy"
    )
    health_score: float = Field(
        ...,
        description="Health score (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        example=0.95
    )
    services: Dict[str, HealthServiceStatus] = Field(
        ...,
        description="Status of individual services"
    )
    agent_state: Optional[str] = Field(
        default=None,
        description="Current agent state",
        example="MONITORING"
    )
    degradation_reasons: List[str] = Field(
        default_factory=list,
        description="Reasons for degraded status"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Health check timestamp"
    )


class ModelPrediction(BaseModel):
    """Model prediction details."""
    
    model_name: str = Field(
        ...,
        description="Model name",
        example="xgboost_BTCUSD_15m"
    )
    prediction: float = Field(
        ...,
        description="Prediction value (-1.0 to +1.0)",
        ge=-1.0,
        le=1.0,
        example=0.75
    )
    confidence: float = Field(
        ...,
        description="Confidence score (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        example=0.85
    )
    reasoning: str = Field(
        ...,
        description="Human-readable reasoning",
        example="Strong bullish signal based on RSI and MACD indicators"
    )


class ReasoningStep(BaseModel):
    """Single step in reasoning chain."""
    
    step_number: int = Field(
        ...,
        description="Step number in chain",
        example=1
    )
    step_name: str = Field(
        ...,
        description="Step name",
        example="Situational Assessment"
    )
    description: str = Field(
        ...,
        description="Step description",
        example="Current market conditions analyzed"
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Evidence items"
    )
    confidence: float = Field(
        ...,
        description="Step confidence (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        example=0.8
    )


class ReasoningChain(BaseModel):
    """Reasoning chain structure."""
    
    chain_id: str = Field(
        ...,
        description="Unique reasoning chain ID",
        example="chain_123456"
    )
    timestamp: datetime = Field(
        ...,
        description="Chain creation timestamp"
    )
    steps: List[ReasoningStep] = Field(
        ...,
        description="Reasoning steps"
    )
    conclusion: str = Field(
        ...,
        description="Final conclusion",
        example="Strong buy signal with high confidence"
    )
    final_confidence: float = Field(
        ...,
        description="Final confidence score (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        example=0.85
    )


class PredictResponse(BaseModel):
    """Prediction response."""
    
    signal: str = Field(
        ...,
        description="Trading signal",
        example="BUY"
    )
    confidence: float = Field(
        ...,
        description="Confidence score (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        example=0.75
    )
    position_size: Optional[Decimal] = Field(
        default=None,
        description="Recommended position size",
        example=0.05
    )
    reasoning_chain: ReasoningChain = Field(
        ...,
        description="Complete reasoning chain"
    )
    model_predictions: List[ModelPrediction] = Field(
        ...,
        description="Individual model predictions"
    )
    market_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Market context used"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Prediction timestamp"
    )


class TradeResponse(BaseModel):
    """Trade execution response."""
    
    trade_id: str = Field(
        ...,
        description="Unique trade ID",
        example="trade_123456"
    )
    symbol: str = Field(
        ...,
        description="Trading symbol",
        example="BTCUSD"
    )
    side: str = Field(
        ...,
        description="Trade side",
        example="BUY"
    )
    quantity: Decimal = Field(
        ...,
        description="Trade quantity",
        example=0.1
    )
    price: Decimal = Field(
        ...,
        description="Execution price",
        example=50000.0
    )
    status: str = Field(
        ...,
        description="Trade status",
        example="EXECUTED"
    )
    executed_at: datetime = Field(
        ...,
        description="Execution timestamp"
    )
    reasoning_chain_id: Optional[str] = Field(
        default=None,
        description="Associated reasoning chain ID",
        example="chain_123456"
    )


class PositionResponse(BaseModel):
    """Position response."""
    
    position_id: str = Field(
        ...,
        description="Unique position ID",
        example="pos_123456"
    )
    symbol: str = Field(
        ...,
        description="Trading symbol",
        example="BTCUSD"
    )
    side: str = Field(
        ...,
        description="Position side",
        example="LONG"
    )
    quantity: Decimal = Field(
        ...,
        description="Position quantity",
        example=0.1
    )
    entry_price: Decimal = Field(
        ...,
        description="Entry price",
        example=50000.0
    )
    current_price: Optional[Decimal] = Field(
        default=None,
        description="Current market price",
        example=51000.0
    )
    unrealized_pnl: Optional[Decimal] = Field(
        default=None,
        description="Unrealized profit/loss",
        example=100.0
    )
    status: str = Field(
        ...,
        description="Position status",
        example="OPEN"
    )
    opened_at: datetime = Field(
        ...,
        description="Position open timestamp"
    )
    stop_loss: Optional[Decimal] = Field(
        default=None,
        description="Stop loss price",
        example=49000.0
    )
    take_profit: Optional[Decimal] = Field(
        default=None,
        description="Take profit price",
        example=52000.0
    )


class PortfolioSummaryResponse(BaseModel):
    """Portfolio summary response."""
    
    total_value: Decimal = Field(
        ...,
        description="Total portfolio value",
        example=10000.0
    )
    available_balance: Decimal = Field(
        ...,
        description="Available balance",
        example=9500.0
    )
    open_positions: int = Field(
        ...,
        description="Number of open positions",
        example=2
    )
    total_unrealized_pnl: Decimal = Field(
        ...,
        description="Total unrealized profit/loss",
        example=150.0
    )
    total_realized_pnl: Decimal = Field(
        ...,
        description="Total realized profit/loss",
        example=250.0
    )
    positions: List[PositionResponse] = Field(
        default_factory=list,
        description="Open positions"
    )


class MarketDataResponse(BaseModel):
    """Market data response."""
    
    symbol: str = Field(
        ...,
        description="Trading symbol",
        example="BTCUSD"
    )
    interval: str = Field(
        ...,
        description="Time interval",
        example="1h"
    )
    candles: List[Dict[str, Any]] = Field(
        ...,
        description="OHLCV candle data"
    )
    latest_price: Decimal = Field(
        ...,
        description="Latest price",
        example=50000.0
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Data timestamp"
    )


class AgentStatusResponse(BaseModel):
    """Agent status response."""
    
    state: str = Field(
        ...,
        description="Agent state",
        example="MONITORING"
    )
    last_update: datetime = Field(
        ...,
        description="Last update timestamp"
    )
    active_symbols: List[str] = Field(
        default_factory=list,
        description="Active trading symbols"
    )
    model_count: int = Field(
        ...,
        description="Number of active models",
        example=5
    )
    health_status: str = Field(
        ...,
        description="Agent health status",
        example="healthy"
    )
    message: Optional[str] = Field(
        default=None,
        description="Status message",
        example="All systems operational"
    )


class ErrorResponse(BaseModel):
    """Error response model."""
    
    error: Dict[str, Any] = Field(
        ...,
        description="Error details"
    )
    
    @classmethod
    def create(cls, code: str, message: str, details: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None):
        """Create error response."""
        error_data = {
            "code": code,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if details:
            error_data["details"] = details
        if request_id:
            error_data["request_id"] = request_id
        return cls(error={"error": error_data})

