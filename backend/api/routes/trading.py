"""
Trading operation endpoints.

Handles prediction requests and trade execution.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
from sqlalchemy.orm import Session
import uuid

from backend.core.database import get_db
from backend.api.models.requests import PredictRequest, ExecuteTradeRequest
from backend.api.models.responses import PredictResponse, TradeResponse, ErrorResponse
from backend.services.agent_service import agent_service
from backend.services.market_service import market_service

router = APIRouter()


@router.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    Request AI prediction for current market conditions.
    
    Returns trading signal with reasoning chain and model predictions.
    """
    
    try:
        # Request prediction from agent
        prediction = await agent_service.get_prediction(
            symbol=request.symbol,
            context=request.context or {}
        )
        
        if not prediction:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable"
            )
        
        return PredictResponse(**prediction)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(e)}"
        )


@router.post("/trade/execute", response_model=TradeResponse)
async def execute_trade(
    request: ExecuteTradeRequest,
    db: Session = Depends(get_db)
):
    """
    Execute a trade order.
    
    Places order via Delta Exchange API through the agent service.
    """
    
    try:
        # Validate order
        if request.order_type == "LIMIT" and request.price is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Price is required for LIMIT orders"
            )
        
        # Request trade execution from agent
        trade_result = await agent_service.execute_trade(
            symbol=request.symbol,
            side=request.side,
            quantity=float(request.quantity),
            order_type=request.order_type,
            price=float(request.price) if request.price else None,
            stop_loss=float(request.stop_loss) if request.stop_loss else None,
            take_profit=float(request.take_profit) if request.take_profit else None
        )
        
        if not trade_result:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Trade execution failed - agent service unavailable"
            )
        
        # Check if trade was successful
        if trade_result.get("status") != "EXECUTED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Trade execution failed: {trade_result.get('error', 'Unknown error')}"
            )
        
        return TradeResponse(**trade_result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Trade execution failed: {str(e)}"
        )

