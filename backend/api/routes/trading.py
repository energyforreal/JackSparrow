"""
Trading operation endpoints.

Handles prediction requests and trade execution.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.models.requests import ExecuteTradeRequest, PredictRequest
from backend.api.models.responses import ErrorResponse, PredictResponse, TradeResponse
from backend.core.database import get_db
from backend.notifications import telegram_notifier
from backend.services.agent_service import agent_service
from backend.services.market_service import market_service
from backend.api.middleware.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    Request AI prediction for current market conditions.
    
    Returns trading signal with reasoning chain and model predictions.
    
    **Request Body:**
    ```json
    {
      "symbol": "BTCUSD",
      "context": {
        "interval": "15m",
        "features": {}
      }
    }
    ```
    
    **Example Response:**
    ```json
    {
      "signal": 0.75,
      "confidence": 0.85,
      "timestamp": "2025-01-27T12:00:00Z",
      "reasoning_chain": [
        {
          "step": 1,
          "reasoning": "Market analysis shows bullish trend",
          "confidence": 0.8
        }
      ],
      "model_predictions": []
    }
    ```
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
    db: AsyncSession = Depends(get_db)
):
    """
    Execute a trade order.
    
    Places order via Delta Exchange API through the agent service.
    
    **Request Body:**
    ```json
    {
      "symbol": "BTCUSD",
      "side": "buy",
      "quantity": 0.1,
      "order_type": "MARKET",
      "price": null
    }
    ```
    
    **Example Response:**
    ```json
    {
      "trade_id": "trade_123",
      "symbol": "BTCUSD",
      "side": "buy",
      "quantity": 0.1,
      "price": 50000.00,
      "status": "filled",
      "executed_at": "2025-01-27T12:00:00Z"
    }
    ```
    
    **Note:** In paper trading mode, orders are simulated and not executed on the exchange.
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
        
        response_payload = TradeResponse(**trade_result)
        
        if telegram_notifier.enabled:
            asyncio.create_task(
                telegram_notifier.notify_trade_execution(
                    symbol=request.symbol,
                    side=request.side,
                    quantity=float(request.quantity),
                    price=float(request.price) if request.price else None,
                    order_type=request.order_type,
                    result=trade_result,
                )
            )
        
        return response_payload
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Trade execution failed: {str(e)}"
        )

