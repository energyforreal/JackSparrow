"""
Pydantic request models for API endpoints.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, validator


class PredictRequest(BaseModel):
    """Request model for prediction endpoint."""
    
    symbol: Optional[str] = Field(
        default="BTCUSD",
        description="Trading symbol",
        example="BTCUSD"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional market context"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTCUSD",
                "context": {}
            }
        }


class ExecuteTradeRequest(BaseModel):
    """Request model for trade execution endpoint."""
    
    symbol: str = Field(
        ...,
        description="Trading symbol",
        example="BTCUSD"
    )
    side: str = Field(
        ...,
        description="Trade side (BUY or SELL)",
        example="BUY"
    )
    quantity: Decimal = Field(
        ...,
        description="Trade quantity",
        gt=0,
        example=0.1
    )
    order_type: str = Field(
        default="MARKET",
        description="Order type",
        example="MARKET"
    )
    price: Optional[Decimal] = Field(
        default=None,
        description="Limit price (required for LIMIT orders)",
        example=None
    )
    stop_loss: Optional[Decimal] = Field(
        default=None,
        description="Stop loss price",
        example=None
    )
    take_profit: Optional[Decimal] = Field(
        default=None,
        description="Take profit price",
        example=None
    )
    
    @validator('side')
    def validate_side(cls, v):
        if v.upper() not in ['BUY', 'SELL']:
            raise ValueError('side must be BUY or SELL')
        return v.upper()
    
    @validator('order_type')
    def validate_order_type(cls, v):
        if v.upper() not in ['MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT']:
            raise ValueError('order_type must be MARKET, LIMIT, STOP, or STOP_LIMIT')
        return v.upper()
    
    @validator('price')
    def validate_price_for_limit(cls, v, values):
        if values.get('order_type') == 'LIMIT' and v is None:
            raise ValueError('price is required for LIMIT orders')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.1,
                "order_type": "MARKET"
            }
        }


class PortfolioRequest(BaseModel):
    """Request model for portfolio endpoints."""
    
    symbol: Optional[str] = Field(
        default=None,
        description="Filter by symbol",
        example="BTCUSD"
    )
    status: Optional[str] = Field(
        default=None,
        description="Filter by position status",
        example="OPEN"
    )
    limit: Optional[int] = Field(
        default=100,
        description="Maximum number of results",
        ge=1,
        le=1000,
        example=100
    )
    offset: Optional[int] = Field(
        default=0,
        description="Offset for pagination",
        ge=0,
        example=0
    )


class MarketDataRequest(BaseModel):
    """Request model for market data endpoints."""
    
    symbol: str = Field(
        ...,
        description="Trading symbol",
        example="BTCUSD"
    )
    interval: Optional[str] = Field(
        default="1h",
        description="Time interval",
        example="1h"
    )
    limit: Optional[int] = Field(
        default=100,
        description="Number of candles",
        ge=1,
        le=1000,
        example=100
    )


class AgentControlRequest(BaseModel):
    """Request model for agent control endpoints."""
    
    action: str = Field(
        ...,
        description="Action to perform",
        example="start"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Action parameters"
    )
    
    @validator('action')
    def validate_action(cls, v):
        valid_actions = ['start', 'stop', 'pause', 'resume', 'restart']
        if v.lower() not in valid_actions:
            raise ValueError(f'action must be one of {valid_actions}')
        return v.lower()
    
    class Config:
        json_schema_extra = {
            "example": {
                "action": "start",
                "parameters": {}
            }
        }

