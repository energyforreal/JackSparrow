"""
Trading operation endpoints.

Handles prediction requests and trade execution.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from backend.api.models.requests import ExecuteTradeRequest, PredictRequest
from backend.api.models.responses import (
    ErrorResponse,
    PredictResponse,
    TradeResponse,
    ReasoningChain,
    ReasoningStep,
    ModelPrediction,
    ModelConsensusEntry,
    ModelReasoningEntry,
)
from backend.core.database import get_db
from backend.notifications import telegram_notifier
from backend.services.agent_service import agent_service
from backend.services.market_service import market_service
from backend.api.middleware.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
logger = structlog.get_logger()


@router.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    **DEPRECATED**: This REST API endpoint is deprecated.

    Use WebSocket command instead:
    ```javascript
    websocket.send(JSON.stringify({
      action: 'command',
      command: 'predict',
      request_id: 'req_123',
      parameters: { symbol: 'BTCUSD' }
    }))
    ```

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
        logger.info(
            "predict_request_received",
            symbol=request.symbol,
            has_context=bool(request.context)
        )
        
        # Request prediction from agent
        response = await agent_service.get_prediction(
            symbol=request.symbol,
            context=request.context or {}
        )
        
        if not response:
            logger.error(
                "predict_agent_no_response",
                symbol=request.symbol,
                message="Agent service returned None"
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable - no response received"
            )
        
        # Check if response indicates error
        if isinstance(response, dict) and not response.get("success", True):
            error_msg = response.get("error", "Unknown error from agent")
            logger.error(
                "predict_agent_error",
                symbol=request.symbol,
                error=error_msg,
                response=response
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Agent service error: {error_msg}"
            )
        
        # Extract data from response (agent returns {"success": True, "data": {...}})
        decision_data = response.get("data", response) if isinstance(response, dict) else response
        
        if not isinstance(decision_data, dict):
            logger.error(
                "predict_invalid_response_format",
                symbol=request.symbol,
                response_type=type(response).__name__,
                response=response
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid response format from agent service"
            )

        # If the agent responded with an explicit error payload (e.g. no models
        # available, no predictions), surface this as an error to the client
        # instead of fabricating a neutral HOLD decision.
        if decision_data.get("error_code") or decision_data.get("error"):
            error_code = decision_data.get("error_code", "AGENT_ERROR")
            error_msg = decision_data.get("error") or f"Agent error: {error_code}"
            logger.error(
                "predict_agent_decision_error_payload",
                symbol=request.symbol,
                error_code=error_code,
                error=error_msg,
                decision_data=decision_data,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Agent cannot produce ML-backed prediction: {error_msg}",
            )
        
        logger.debug(
            "predict_decision_received",
            symbol=request.symbol,
            decision_keys=list(decision_data.keys())
        )
        
        # Transform agent response to PredictResponse format
        try:
            # Extract and transform reasoning_chain
            reasoning_chain_dict = decision_data.get("reasoning_chain", {})
            if isinstance(reasoning_chain_dict, dict):
                # Convert steps if present
                steps = reasoning_chain_dict.get("steps", [])
                reasoning_steps = [
                    ReasoningStep(**step) if isinstance(step, dict) else step
                    for step in steps
                ]
                
                reasoning_chain = ReasoningChain(
                    chain_id=reasoning_chain_dict.get("chain_id", "unknown"),
                    timestamp=datetime.fromisoformat(
                        reasoning_chain_dict["timestamp"].replace("Z", "+00:00")
                    ) if "timestamp" in reasoning_chain_dict else datetime.utcnow(),
                    steps=reasoning_steps,
                    conclusion=reasoning_chain_dict.get("conclusion", "No conclusion"),
                    final_confidence=float(reasoning_chain_dict.get("final_confidence", 0.0))
                )
            else:
                # Create minimal reasoning chain if missing
                reasoning_chain = ReasoningChain(
                    chain_id="unknown",
                    timestamp=datetime.utcnow(),
                    steps=[],
                    conclusion="No reasoning chain available",
                    final_confidence=0.0
                )
            
            # Extract and transform model_predictions
            model_predictions_list = decision_data.get("model_predictions", [])
            model_predictions = [
                ModelPrediction(**pred) if isinstance(pred, dict) else pred
                for pred in model_predictions_list
            ]
            
            # Extract signal and confidence
            signal = decision_data.get("signal", "HOLD")
            confidence = float(decision_data.get("confidence", 0.0))
            
            # Extract position_size and convert to Decimal
            position_size_val = decision_data.get("position_size")
            position_size = Decimal(str(position_size_val)) if position_size_val is not None else None
            
            # Extract timestamp
            timestamp_str = decision_data.get("timestamp")
            if timestamp_str:
                try:
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    else:
                        timestamp = datetime.utcnow()
                except (ValueError, AttributeError):
                    timestamp = datetime.utcnow()
            else:
                timestamp = datetime.utcnow()
            
            # Extract market_context (may include features, etc.)
            market_context = decision_data.get("market_context", {}) or {}
            if not market_context:
                # Try to construct from available data
                market_context = {
                    "feature_quality": decision_data.get("feature_quality"),
                    "symbol": request.symbol
                }

            # Derive per-model consensus signals and reasoning so the frontend
            # can render model-level breakdowns even without WebSocket updates.
            def _map_prediction_to_signal(pred_value: float) -> str:
                """Map a continuous prediction in [-1, 1] to a discrete signal."""
                if abs(pred_value) < 0.2:
                    return "HOLD"
                if pred_value > 0.6:
                    return "STRONG_BUY"
                if pred_value > 0.2:
                    return "BUY"
                if pred_value < -0.6:
                    return "STRONG_SELL"
                return "SELL"

            model_consensus: list[ModelConsensusEntry] = []
            individual_model_reasoning: list[ModelReasoningEntry] = []

            for pred in model_predictions:
                try:
                    model_consensus.append(
                        ModelConsensusEntry(
                            model_name=pred.model_name,
                            signal=_map_prediction_to_signal(pred.prediction),
                            confidence=float(pred.confidence),
                        )
                    )
                    individual_model_reasoning.append(
                        ModelReasoningEntry(
                            model_name=pred.model_name,
                            reasoning=pred.reasoning,
                            confidence=float(pred.confidence),
                        )
                    )
                except Exception as model_error:
                    logger.warning(
                        "predict_model_consensus_build_failed",
                        model_name=getattr(pred, "model_name", "unknown"),
                        error=str(model_error),
                    )
            
            # Create PredictResponse
            predict_response = PredictResponse(
                signal=signal,
                confidence=confidence,
                position_size=position_size,
                reasoning_chain=reasoning_chain,
                model_predictions=model_predictions,
                model_consensus=model_consensus,
                individual_model_reasoning=individual_model_reasoning,
                market_context=market_context,
                timestamp=timestamp
            )
            
            logger.warning(
                "predict_endpoint_deprecated",
                symbol=request.symbol,
                message="REST API /predict endpoint is deprecated. Use WebSocket command 'predict' instead.",
                migration_guide="Send: {action: 'command', command: 'predict', request_id: '...', parameters: {symbol: '...'}}"
            )

            logger.info(
                "predict_success",
                symbol=request.symbol,
                signal=signal,
                confidence=confidence
            )

            return predict_response
            
        except Exception as transform_error:
            logger.error(
                "predict_response_transform_failed",
                symbol=request.symbol,
                error=str(transform_error),
                error_type=type(transform_error).__name__,
                decision_data=decision_data,
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to transform prediction response: {str(transform_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "predict_endpoint_error",
            symbol=request.symbol if hasattr(request, 'symbol') else None,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
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
    **DEPRECATED**: This REST API endpoint is deprecated.

    Use WebSocket command instead:
    ```javascript
    websocket.send(JSON.stringify({
      action: 'command',
      command: 'execute_trade',
      request_id: 'req_123',
      parameters: {
        symbol: 'BTCUSD',
        side: 'buy',
        quantity: 0.1,
        order_type: 'MARKET'
      }
    }))
    ```

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
        
        # Invalidate portfolio cache when trade is executed
        from backend.core.redis import delete_cache
        await delete_cache("portfolio:summary")
        await delete_cache(f"portfolio:performance:30")  # Invalidate common performance cache
        logger.debug("portfolio_cache_invalidated", reason="trade_executed")
        
        response_payload = TradeResponse(**trade_result)
        
        logger.warning(
            "execute_trade_endpoint_deprecated",
            symbol=request.symbol,
            side=request.side,
            quantity=float(request.quantity),
            message="REST API /trade/execute endpoint is deprecated. Use WebSocket command 'execute_trade' instead.",
            migration_guide="Send: {action: 'command', command: 'execute_trade', request_id: '...', parameters: {...}}"
        )

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

