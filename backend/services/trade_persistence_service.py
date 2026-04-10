"""
Trade Persistence Service.

Handles database persistence for trades and positions.
Integrates trading execution with portfolio management.
"""

from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, cast, String
from sqlalchemy.types import Numeric
import structlog
import uuid

from backend.core.database import (
    Trade, Position, TradeStatus, PositionStatus, TradeSide, OrderType,
    AsyncSessionLocal
)

logger = structlog.get_logger()


class TradePersistenceService:
    """Service for persisting trades and positions to database."""
    
    async def create_trade_and_position(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        order_type: str = "MARKET",
        reasoning_chain_id: Optional[str] = None,
        model_predictions: Optional[Dict[str, Any]] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        executed_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Create Trade and Position records in database.
        
        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            side: Trade side (BUY or SELL)
            quantity: Trade quantity
            fill_price: Fill price
            order_type: Order type (default: MARKET)
            reasoning_chain_id: Reasoning chain ID for traceability
            model_predictions: Model predictions that led to trade
            stop_loss: Stop loss price
            take_profit: Take profit price
            executed_at: Execution timestamp (default: now)
            
        Returns:
            Dictionary with created trade and position IDs
        """
        logger.info(
            "trade_persistence_service_create_called",
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            order_type=order_type,
            message="TradePersistenceService.create_trade_and_position called"
        )
        
        # Validate inputs
        if not trade_id:
            error_msg = "Trade ID is required"
            logger.error("trade_persistence_service_validation_failed", error=error_msg)
            raise ValueError(error_msg)
        
        if not symbol:
            error_msg = "Symbol is required"
            logger.error("trade_persistence_service_validation_failed", error=error_msg)
            raise ValueError(error_msg)
        
        if not side or side.upper() not in ["BUY", "SELL"]:
            error_msg = f"Invalid side: {side}. Must be BUY or SELL"
            logger.error("trade_persistence_service_validation_failed", side=side, error=error_msg)
            raise ValueError(error_msg)
        
        if quantity is None or quantity <= 0:
            error_msg = f"Invalid quantity: {quantity}. Must be greater than zero"
            logger.error("trade_persistence_service_validation_failed", quantity=quantity, error=error_msg)
            raise ValueError(error_msg)
        
        if fill_price is None or fill_price <= 0:
            error_msg = f"Invalid fill_price: {fill_price}. Must be greater than zero"
            logger.error("trade_persistence_service_validation_failed", fill_price=fill_price, error=error_msg)
            raise ValueError(error_msg)
        
        async with AsyncSessionLocal() as session:
            try:
                executed_at = executed_at or datetime.utcnow()
                
                # Convert side to TradeSide enum
                trade_side = TradeSide.BUY if side.upper() == "BUY" else TradeSide.SELL
                from backend.core.config import settings
                
                # For BUY trades, validate we have sufficient available balance
                if trade_side == TradeSide.BUY and not bool(getattr(settings, "paper_trading_mode", True)):
                    required_balance_usd = Decimal(str(quantity * fill_price))
                    initial_balance_inr = Decimal(str(getattr(settings, 'initial_balance', 20000.0)))
                    
                    # Get USD/INR rate
                    from backend.services.fx_rate_service import get_usdinr_rate
                    usdinr_rate = Decimal(str(await get_usdinr_rate()))
                    
                    # Calculate available balance in USD
                    # Available balance = initial_balance/rate + realized_PnL - open_positions_value
                    open_positions_agg = select(
                        func.sum(
                            case(
                                ((Position.entry_price.isnot(None)) & (Position.quantity.isnot(None)),
                                 Position.entry_price * Position.quantity),
                                else_=0
                            )
                        ).label('positions_value')
                    ).where(cast(Position.status, String) == PositionStatus.OPEN.value)
                    
                    result = await session.execute(open_positions_agg)
                    agg_result = result.first()
                    positions_value_usd = Decimal(str(agg_result.positions_value or 0))
                    
                    # Get realized PnL
                    closed_positions_agg = select(
                        func.sum(
                            case(
                                (Position.realized_pnl.isnot(None), Position.realized_pnl),
                                else_=0
                            )
                        ).label('total_realized_pnl')
                    ).where(Position.status == PositionStatus.CLOSED)
                    
                    result = await session.execute(closed_positions_agg)
                    agg_result = result.first()
                    realized_pnl_usd = Decimal(str(agg_result.total_realized_pnl or 0))
                    
                    # Calculate available balance in USD
                    # initial_balance_inr is in INR, convert to USD
                    initial_balance_usd = initial_balance_inr / usdinr_rate
                    available_balance_usd = initial_balance_usd + realized_pnl_usd - positions_value_usd
                    
                    # Check if we have sufficient balance
                    if required_balance_usd > available_balance_usd:
                        error_msg = f"Insufficient balance: Required ${required_balance_usd:.2f}, Available ${available_balance_usd:.2f}"
                        logger.error(
                            "trade_persistence_service_insufficient_balance",
                            required_usd=float(required_balance_usd),
                            available_usd=float(available_balance_usd),
                            symbol=symbol,
                            quantity=quantity,
                            fill_price=fill_price,
                            error=error_msg
                        )
                        raise ValueError(error_msg)
                    
                    logger.info(
                        "budget_validation_passed",
                        required_usd=float(required_balance_usd),
                        available_usd=float(available_balance_usd),
                        remaining_usd=float(available_balance_usd - required_balance_usd)
                    )
                elif trade_side == TradeSide.BUY:
                    logger.debug(
                        "trade_persistence_budget_check_skipped_paper_mode",
                        symbol=symbol,
                        quantity=quantity,
                        fill_price=fill_price,
                        message="Skipping duplicate balance check in paper mode; agent risk/margin gates already validated entry",
                    )
                
                logger.debug(
                    "trade_persistence_service_starting_transaction",
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price
                )
                
                # Check if trade already exists
                existing_trade = await session.execute(
                    select(Trade).where(Trade.trade_id == trade_id)
                )
                if existing_trade.scalar_one_or_none():
                    logger.warning(
                        "trade_already_exists",
                        trade_id=trade_id,
                        symbol=symbol,
                        message="Trade already exists in database, skipping creation"
                    )
                    await session.rollback()
                    return {"trade_id": trade_id, "position_id": None}
                
                # Create Trade record
                trade = Trade(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=trade_side,
                    quantity=Decimal(str(quantity)),
                    price=Decimal(str(fill_price)),
                    order_type=OrderType.MARKET if order_type.upper() == "MARKET" else OrderType.LIMIT,
                    status=TradeStatus.EXECUTED,
                    executed_at=executed_at,
                    reasoning_chain_id=reasoning_chain_id,
                    model_predictions=model_predictions
                )
                session.add(trade)
                
                # Create Position record
                position_id = str(uuid.uuid4())
                position = Position(
                    position_id=position_id,
                    symbol=symbol,
                    side=trade_side,
                    quantity=Decimal(str(quantity)),
                    entry_price=Decimal(str(fill_price)),
                    current_price=Decimal(str(fill_price)),  # Initially same as entry
                    unrealized_pnl=Decimal("0.0"),  # No PnL at entry
                    opened_at=executed_at,
                    status=PositionStatus.OPEN,
                    stop_loss=Decimal(str(stop_loss)) if stop_loss else None,
                    take_profit=Decimal(str(take_profit)) if take_profit else None
                )
                session.add(position)
                
                await session.commit()
                
                logger.info(
                    "trade_and_position_created",
                    trade_id=trade_id,
                    position_id=position_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    executed_at=executed_at.isoformat(),
                    message="Trade and position records created successfully in database"
                )
                
                return {
                    "trade_id": trade_id,
                    "position_id": position_id,
                    "success": True
                }
                
            except Exception as e:
                await session.rollback()
                logger.error(
                    "trade_and_position_creation_failed",
                    trade_id=trade_id,
                    symbol=symbol,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                raise
    
    async def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        closed_at: Optional[datetime] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        entry_price: Optional[float] = None,
        quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Close a position and record exit details.
        
        Args:
            position_id: Position identifier
            exit_price: Exit price
            exit_reason: Reason for exit (stop_loss, take_profit, signal_reversal)
            pnl: Profit or loss amount
            closed_at: Close timestamp (default: now)
            
        Returns:
            Dictionary with updated position details
        """
        async with AsyncSessionLocal() as session:
            try:
                closed_at = closed_at or datetime.utcnow()
                
                # Find position - prioritize fallback lookup by symbol when available
                position = None
                
                if symbol:
                    # Use symbol-based lookup as primary method for agent-generated position_ids
                    side_enum = None
                    if isinstance(side, str):
                        side_upper = side.strip().upper()
                        if side_upper in {"BUY", "LONG"}:
                            side_enum = TradeSide.BUY
                        elif side_upper in {"SELL", "SHORT"}:
                            side_enum = TradeSide.SELL

                    symbol_query = select(Position).where(
                        Position.symbol == symbol,
                        Position.status == PositionStatus.OPEN,
                    )
                    if side_enum is not None:
                        symbol_query = symbol_query.where(Position.side == side_enum)
                    symbol_query = symbol_query.order_by(Position.opened_at.desc()).limit(1)

                    symbol_result = await session.execute(symbol_query)
                    position = symbol_result.scalar_one_or_none()

                    if position:
                        logger.debug(
                            "position_close_symbol_lookup_used",
                            requested_position_id=position_id,
                            resolved_position_id=position.position_id,
                            symbol=symbol,
                            side=side,
                            message="Resolved close request using symbol-based lookup",
                        )
                    else:
                        logger.warning(
                            "position_close_symbol_lookup_failed",
                            position_id=position_id,
                            symbol=symbol,
                            side=side,
                            message="No open position found for symbol/side",
                        )
                else:
                    # Fallback to position_id lookup if no symbol provided
                    result = await session.execute(
                        select(Position).where(Position.position_id == position_id)
                    )
                    position = result.scalar_one_or_none()
                
                if not position:
                    logger.warning(
                        "position_not_found_for_close",
                        position_id=position_id,
                        message="Position not found in database"
                    )
                    await session.rollback()
                    return {"success": False, "error": "Position not found"}
                
                if position.status == PositionStatus.CLOSED:
                    logger.warning(
                        "position_already_closed",
                        position_id=position_id,
                        message="Position is already closed"
                    )
                    await session.rollback()
                    return {"success": False, "error": "Position already closed"}
                
                # Update position with exit details
                position.current_price = Decimal(str(exit_price))
                position.realized_pnl = Decimal(str(pnl))  # Store realized PnL in dedicated column
                position.unrealized_pnl = Decimal("0")  # Zero out unrealized PnL for closed position
                position.closed_at = closed_at
                position.status = PositionStatus.CLOSED
                
                await session.commit()
                
                # Determine if profit or loss
                is_profit = pnl > 0
                is_loss = pnl < 0
                
                logger.info(
                    "position_closed",
                    position_id=position_id,
                    symbol=position.symbol,
                    entry_price=float(position.entry_price),
                    exit_price=exit_price,
                    pnl=pnl,
                    exit_reason=exit_reason,
                    is_profit=is_profit,
                    is_loss=is_loss,
                    message=f"Position closed: {'PROFIT' if is_profit else 'LOSS' if is_loss else 'BREAKEVEN'}"
                )
                
                return {
                    "success": True,
                    "position_id": position_id,
                    "symbol": position.symbol,
                    "entry_price": float(position.entry_price),
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "exit_reason": exit_reason,
                    "is_profit": is_profit,
                    "is_loss": is_loss,
                    "closed_at": closed_at.isoformat()
                }
                
            except Exception as e:
                await session.rollback()
                logger.error(
                    "position_close_failed",
                    position_id=position_id,
                    exit_price=exit_price,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                raise
    
    async def update_position_price(
        self,
        position_id: str,
        current_price: float
    ) -> bool:
        """Update position current price and recalculate unrealized PnL.
        
        Args:
            position_id: Position identifier
            current_price: Current market price
            
        Returns:
            True if updated successfully, False otherwise
        """
        async with AsyncSessionLocal() as session:
            try:
                result = await session.execute(
                    select(Position).where(
                        Position.position_id == position_id,
                        Position.status == PositionStatus.OPEN
                    )
                )
                position = result.scalar_one_or_none()
                
                if not position:
                    return False
                
                # Update current price
                position.current_price = Decimal(str(current_price))
                
                # Recalculate unrealized PnL
                if position.side == TradeSide.BUY:
                    unrealized_pnl = (Decimal(str(current_price)) - position.entry_price) * position.quantity
                else:  # SELL
                    unrealized_pnl = (position.entry_price - Decimal(str(current_price))) * position.quantity
                
                position.unrealized_pnl = unrealized_pnl
                
                await session.commit()
                return True
                
            except Exception as e:
                await session.rollback()
                logger.error(
                    "position_price_update_failed",
                    position_id=position_id,
                    current_price=current_price,
                    error=str(e),
                    exc_info=True
                )
                return False


# Global service instance
trade_persistence_service = TradePersistenceService()
