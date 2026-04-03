"""
Risk Manager - Comprehensive risk assessment and position sizing.

Implements advanced risk management including portfolio optimization,
position sizing, drawdown control, and Kelly Criterion calculations.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import statistics
import structlog

logger = structlog.get_logger()


class Position:
    """Represents a trading position."""

    def __init__(self, symbol: str, side: str, size: float, entry_price: float,
                 entry_time: datetime, stop_loss: Optional[float] = None,
                 take_profit: Optional[float] = None):
        self.symbol = symbol
        self.side = side  # 'long' or 'short'
        self.size = size  # Position size in base currency
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.current_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.unrealized_pnl = 0.0
        self.peak_value = entry_price * size

    def update_price(self, new_price: float):
        """Update position with new price."""
        self.current_price = new_price

        # Calculate unrealized P&L
        if self.side == 'long':
            self.unrealized_pnl = (new_price - self.entry_price) * self.size
        else:  # short
            self.unrealized_pnl = (self.entry_price - new_price) * self.size

        # Update peak value for drawdown calculation
        current_value = self.entry_price * self.size + self.unrealized_pnl
        self.peak_value = max(self.peak_value, current_value)

    def get_drawdown(self) -> float:
        """Calculate current drawdown from peak."""
        current_value = self.entry_price * self.size + self.unrealized_pnl
        if self.peak_value > 0:
            return (self.peak_value - current_value) / self.peak_value
        return 0.0

    def should_close(self) -> Tuple[bool, str]:
        """Check if position should be closed based on stops."""
        if self.stop_loss:
            if self.side == 'long' and self.current_price <= self.stop_loss:
                return True, "stop_loss_hit"
            elif self.side == 'short' and self.current_price >= self.stop_loss:
                return True, "stop_loss_hit"

        if self.take_profit:
            if self.side == 'long' and self.current_price >= self.take_profit:
                return True, "take_profit_hit"
            elif self.side == 'short' and self.current_price <= self.take_profit:
                return True, "take_profit_hit"

        return False, ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "unrealized_pnl": self.unrealized_pnl,
            "drawdown": self.get_drawdown()
        }


class Portfolio:
    """Represents the trading portfolio."""

    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.cash_balance = initial_balance
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Dict[str, Any]] = []
        self.peak_portfolio_value = initial_balance
        self.current_portfolio_value = initial_balance

    @property
    def total_value(self) -> float:
        """Calculate total portfolio value."""
        position_values = sum(pos.entry_price * pos.size + pos.unrealized_pnl
                            for pos in self.positions.values())
        return self.cash_balance + position_values

    @property
    def total_exposure(self) -> float:
        """Calculate total position exposure."""
        return sum(pos.entry_price * pos.size for pos in self.positions.values())

    @property
    def leverage_ratio(self) -> float:
        """Calculate current leverage ratio."""
        if self.cash_balance <= 0:
            return float('inf')
        return self.total_exposure / self.cash_balance

    def add_position(self, position: Position):
        """Add a position to the portfolio."""
        self.positions[position.symbol] = position
        self._update_portfolio_value()

    def remove_position(self, symbol: str) -> Optional[Position]:
        """Remove a position from portfolio."""
        position = self.positions.pop(symbol, None)
        if position:
            # Add realized P&L to cash balance
            self.cash_balance += position.unrealized_pnl
            self._update_portfolio_value()
        return position

    def update_position_price(self, symbol: str, new_price: float):
        """Update position price."""
        if symbol in self.positions:
            self.positions[symbol].update_price(new_price)
            self._update_portfolio_value()

    def _update_portfolio_value(self):
        """Update portfolio value and peak tracking."""
        self.current_portfolio_value = self.total_value
        self.peak_portfolio_value = max(self.peak_portfolio_value, self.current_portfolio_value)

    def get_drawdown(self) -> float:
        """Calculate current portfolio drawdown."""
        if self.peak_portfolio_value > 0:
            return (self.peak_portfolio_value - self.current_portfolio_value) / self.peak_portfolio_value
        return 0.0

    def get_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio from trade history."""
        if len(self.trade_history) < 2:
            return 0.0

        # Calculate daily returns
        returns = []
        for trade in self.trade_history:
            pnl = trade.get("pnl", 0)
            portfolio_value = trade.get("portfolio_value_before", self.initial_balance)
            if portfolio_value > 0:
                returns.append(pnl / portfolio_value)

        if not returns:
            return 0.0

        avg_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0

        if std_return == 0:
            return float('inf') if avg_return > 0 else float('-inf')

        return (avg_return - risk_free_rate) / std_return

    def record_trade(self, trade_details: Dict[str, Any]):
        """Record a completed trade."""
        self.trade_history.append({
            **trade_details,
            "timestamp": datetime.utcnow(),
            "portfolio_value_before": self.current_portfolio_value
        })

        # Update cash balance with realized P&L
        pnl = trade_details.get("pnl", 0)
        self.cash_balance += pnl
        self._update_portfolio_value()


class RiskAssessment:
    """Comprehensive risk assessment result."""

    def __init__(self):
        self.overall_risk_level: str = "low"  # low, medium, high, critical
        self.max_position_size: float = 0.0
        self.portfolio_risk_score: float = 0.0  # 0-1 scale
        self.position_limit: int = 5
        self.can_trade: bool = True
        self.risk_factors: Dict[str, Any] = {}
        self.recommendations: List[str] = []
        self.emergency_actions: List[str] = []
        self.portfolio_heat: float = 0.0  # Portfolio heat calculation
        self.max_drawdown: float = 0.0  # Maximum drawdown

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "overall_risk_level": self.overall_risk_level,
            "max_position_size": self.max_position_size,
            "portfolio_risk_score": self.portfolio_risk_score,
            "position_limit": self.position_limit,
            "can_trade": self.can_trade,
            "risk_factors": self.risk_factors,
            "recommendations": self.recommendations,
            "emergency_actions": self.emergency_actions,
            "portfolio_heat": self.portfolio_heat,
            "max_drawdown": self.max_drawdown
        }


class RiskManager:
    """
    Advanced risk management system.

    Implements Kelly Criterion, portfolio optimization, drawdown control,
    and comprehensive risk assessment.
    """

    def __init__(self, config=None):
        self.portfolio: Optional[Portfolio] = None
        self.config = config
        
        # Load risk limits from config or use defaults
        if config:
            self.risk_limits = {
                "max_portfolio_risk": 0.02,  # 2% max loss per trade (conservative)
                "max_daily_loss": config.max_daily_loss,  # From environment
                "max_drawdown": config.max_drawdown,  # From environment
                "max_leverage": 2.0,  # 2x max leverage
                "max_open_positions": 5,
                "min_position_size": 0.01,  # 1% min position
                "max_position_size": config.max_position_size,  # From environment
                "max_portfolio_heat": config.max_portfolio_heat,  # From environment
                "max_correlation": 0.7  # Max correlation between positions
            }
        else:
            # Fallback defaults - more conservative
            self.risk_limits = {
                "max_portfolio_risk": 0.02,  # 2% max loss per trade
                "max_daily_loss": 0.05,  # 5% max daily loss
                "max_drawdown": 0.15,  # 15% max drawdown
                "max_leverage": 2.0,  # 2x max leverage
                "max_open_positions": 5,
                "min_position_size": 0.01,  # 1% min position
                "max_position_size": 0.10,  # 10% max position
                "max_portfolio_heat": 0.30,  # 30% max portfolio heat
                "max_correlation": 0.7  # Max correlation between positions
            }
        self.volatility_adjustments = {
            "low": 1.0,      # Normal sizing
            "medium": 0.7,   # Reduce by 30%
            "high": 0.4,     # Reduce by 60%
            "extreme": 0.1   # Reduce by 90%
        }
        self._initialized = False

    async def initialize(self, initial_balance: float = 10000.0):
        """Initialize risk manager."""
        self.portfolio = Portfolio(initial_balance)
        self._initialized = True
        logger.info("risk_manager_initialized",
                   initial_balance=initial_balance,
                   risk_limits=self.risk_limits)

    async def shutdown(self):
        """Shutdown risk manager."""
        self._initialized = False
        logger.info("risk_manager_shutdown")

    async def assess_portfolio_risk(self, current_prices: Optional[Dict[str, float]] = None) -> RiskAssessment:
        """
        Perform comprehensive portfolio risk assessment.

        Args:
            current_prices: Current market prices for portfolio positions

        Returns:
            RiskAssessment with detailed risk analysis
        """
        if not self._initialized or not self.portfolio:
            assessment = RiskAssessment()
            assessment.can_trade = False
            assessment.recommendations.append("Risk manager not initialized")
            return assessment

        assessment = RiskAssessment()

        # Update position prices if provided
        if current_prices:
            for symbol, price in current_prices.items():
                self.portfolio.update_position_price(symbol, price)

        # Calculate risk factors
        assessment.risk_factors = {
            "portfolio_value": self.portfolio.total_value,
            "cash_balance": self.portfolio.cash_balance,
            "total_exposure": self.portfolio.total_exposure,
            "leverage_ratio": self.portfolio.leverage_ratio,
            "drawdown": self.portfolio.get_drawdown(),
            "open_positions": len(self.portfolio.positions),
            "sharpe_ratio": self.portfolio.get_sharpe_ratio(),
            "daily_pnl": 0.0  # Would come from context manager
        }

        # Assess individual risk factors
        risk_score = 0.0

        # Drawdown risk
        drawdown = assessment.risk_factors["drawdown"]
        if drawdown > self.risk_limits["max_drawdown"]:
            risk_score += 0.4
            assessment.emergency_actions.append("Portfolio drawdown exceeds limit - consider reducing exposure")
        elif drawdown > self.risk_limits["max_drawdown"] * 0.7:
            risk_score += 0.2
            assessment.recommendations.append("Portfolio drawdown approaching limit")

        # Leverage risk
        leverage = assessment.risk_factors["leverage_ratio"]
        if leverage > self.risk_limits["max_leverage"]:
            risk_score += 0.3
            assessment.emergency_actions.append("Leverage exceeds limit - reduce position sizes")
        elif leverage > self.risk_limits["max_leverage"] * 0.8:
            risk_score += 0.15
            assessment.recommendations.append("Leverage approaching limit")

        # Position count risk
        position_count = assessment.risk_factors["open_positions"]
        if position_count >= self.risk_limits["max_open_positions"]:
            risk_score += 0.2
            assessment.can_trade = False
            assessment.recommendations.append("Maximum open positions reached")
        elif position_count > self.risk_limits["max_open_positions"] * 0.8:
            risk_score += 0.1
            assessment.recommendations.append("Approaching maximum open positions")

        # Concentration risk (simplified)
        if self.portfolio.total_exposure > 0:
            max_position = max((pos.entry_price * pos.size for pos in self.portfolio.positions.values()), default=0)
            concentration_ratio = max_position / self.portfolio.total_exposure
            if concentration_ratio > 0.5:  # >50% in one position
                risk_score += 0.15
                assessment.recommendations.append("High concentration in single position")

        assessment.portfolio_risk_score = min(1.0, risk_score)
        
        # Calculate portfolio heat (total risk exposure)
        total_risk_exposure = 0.0
        for position in self.portfolio.positions.values():
            position_risk = abs(position.unrealized_pnl) / self.portfolio.total_value if self.portfolio.total_value > 0 else 0.0
            total_risk_exposure += position_risk
        
        assessment.portfolio_heat = total_risk_exposure
        assessment.max_drawdown = self.portfolio.get_drawdown()

        # Determine overall risk level
        if risk_score >= 0.6:
            assessment.overall_risk_level = "critical"
            assessment.can_trade = False
        elif risk_score >= 0.4:
            assessment.overall_risk_level = "high"
            assessment.max_position_size = self.risk_limits["max_position_size"] * 0.5
        elif risk_score >= 0.2:
            assessment.overall_risk_level = "medium"
            assessment.max_position_size = self.risk_limits["max_position_size"] * 0.75
        else:
            assessment.overall_risk_level = "low"
            assessment.max_position_size = self.risk_limits["max_position_size"]

        assessment.position_limit = max(1, self.risk_limits["max_open_positions"] - len(self.portfolio.positions))

        logger.info("portfolio_risk_assessed",
                   risk_level=assessment.overall_risk_level,
                   risk_score=assessment.portfolio_risk_score,
                   can_trade=assessment.can_trade,
                   recommendations=len(assessment.recommendations))

        return assessment

    def calculate_position_size(
        self,
        mark_price: float,
        confidence: float,
        funding_rate: float = 0.0,
        volatility: float = 0.0,
        return_dict: bool = False,
    ) -> float:
        """
        Calculate position sizing for perpetual futures.

        Returns either position size fraction (default) or detailed sizing dict when return_dict=True.
        """
        if not self._initialized or not self.portfolio:
            return 0.0 if not return_dict else {
                "lots": 0,
                "leverage": 0,
                "margin_usd": 0.0,
                "liq_price_long": 0.0,
                "liq_price_short": 0.0,
                "notional_usd": 0.0,
            }

        # Base signal strength and consensus
        base_strength = max(0.0, min(1.0, confidence))

        # Funding rate penalty
        if abs(funding_rate) > 0.0003:
            fpen = 0.5
        else:
            fpen = 1.0

        # Leverage caps
        min_lev = max(1, int(getattr(self.config, 'min_leverage', 1)))
        default_lev = max(1, int(getattr(self.config, 'default_leverage', 5)))
        max_lev = max(min_lev, int(getattr(self.config, 'max_leverage', 20)))

        leverage = max(min_lev, min(max_lev, int(round(default_lev * base_strength * fpen))))
        if leverage < min_lev:
            leverage = min_lev

        # Volatility scaling
        vol_mult = 1.0
        if volatility > 0.05:
            vol_mult = 0.5
        elif volatility > 0.03:
            vol_mult = 0.7

        target_pct = self.risk_limits.get("max_position_size", 0.1) * base_strength * vol_mult * fpen
        target_pct = max(self.risk_limits.get("min_position_size", 0.01), min(target_pct, self.risk_limits.get("max_position_size", 0.1)))

        # margin and lots
        from agent.core.futures_utils import price_to_lots, calculate_liquidation_price

        available_margin = self.portfolio.cash_balance
        margin_to_use = available_margin * target_pct
        lots = price_to_lots(
            usd_margin=margin_to_use,
            btc_price=mark_price,
            leverage=leverage,
            contract_value_btc=float(getattr(self.config, 'contract_value_btc', 0.001)),
            max_lots=int(getattr(self.config, 'max_lots_per_order', 100)),
            min_lots=int(getattr(self.config, 'min_lot_size', 1)),
        )

        notional_usd = lots * mark_price * float(getattr(self.config, 'contract_value_btc', 0.001))
        liq_long = calculate_liquidation_price(mark_price, leverage, 'long')
        liq_short = calculate_liquidation_price(mark_price, leverage, 'short')

        position_size = max(0.0, min(1.0, target_pct))

        logger.debug("position_size_calculated_futures",
                     mark_price=mark_price,
                     confidence=confidence,
                     funding_rate=funding_rate,
                     volatility=volatility,
                     leverage=leverage,
                     lots=lots,
                     target_pct=target_pct,
                     position_size=position_size)

        if return_dict:
            return {
                "lots": lots,
                "leverage": leverage,
                "margin_usd": margin_to_use,
                "liq_price_long": liq_long,
                "liq_price_short": liq_short,
                "notional_usd": notional_usd,
                "position_size": position_size,
            }

        return position_size

    async def assess_risk(self, symbol: str, side: str, proposed_size: float,
                         entry_price: float, market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Assess risk for a proposed trade.

        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            proposed_size: Proposed position size (0-1 portfolio fraction)
            entry_price: Entry price
            market_context: Additional market context

        Returns:
            Risk assessment with risk level and recommendations
        """
        if not self._initialized or not self.portfolio:
            return {
                "risk_level": "unknown",
                "can_trade": False,
                "reason": "Risk manager not initialized",
                "recommendations": ["Initialize risk manager"]
            }

        # Get portfolio risk assessment
        portfolio_risk = await self.assess_portfolio_risk()

        # Calculate position risk
        position_value = proposed_size * self.portfolio.total_value
        max_position_risk = self.risk_limits["max_position_size"] * self.portfolio.total_value

        risk_assessment = {
            "risk_level": "low",
            "can_trade": True,
            "position_risk": position_value / self.portfolio.total_value,
            "portfolio_heat": portfolio_risk.portfolio_heat,
            "recommendations": []
        }

        # Assess risk level
        if portfolio_risk.portfolio_heat > 0.15:  # >15% portfolio at risk
            risk_assessment["risk_level"] = "high"
            risk_assessment["can_trade"] = False
            risk_assessment["recommendations"].append("Portfolio heat too high - reduce exposure")
        elif portfolio_risk.portfolio_heat > 0.10:  # >10% portfolio at risk
            risk_assessment["risk_level"] = "medium"
            risk_assessment["recommendations"].append("Monitor portfolio heat closely")
        elif position_value > max_position_risk:
            risk_assessment["risk_level"] = "medium"
            risk_assessment["recommendations"].append("Position size exceeds recommended limit")

        return risk_assessment

    async def check_risk_limits(self, symbol: str = None) -> Dict[str, Any]:
        """
        Check if current portfolio is within risk limits.

        Args:
            symbol: Optional symbol to check specific position risk

        Returns:
            Risk limit check results
        """
        if not self._initialized or not self.portfolio:
            return {
                "within_limits": False,
                "reason": "Risk manager not initialized",
                "violations": ["Risk manager not available"]
            }

        violations = []
        portfolio_risk = await self.assess_portfolio_risk()

        # Check portfolio heat
        if portfolio_risk.portfolio_heat > self.risk_limits.get("max_portfolio_heat", 0.3):
            violations.append(f"Portfolio heat {portfolio_risk.portfolio_heat:.1%} exceeds limit {self.risk_limits.get('max_portfolio_heat', 0.3):.1%}")

        # Check drawdown
        if portfolio_risk.max_drawdown > self.risk_limits["max_drawdown"]:
            violations.append(f"Drawdown {portfolio_risk.max_drawdown:.1%} exceeds limit {self.risk_limits['max_drawdown']:.1%}")

        # Check position sizes
        for position in self.portfolio.positions.values():
            position_size_pct = (position.entry_price * position.size) / self.portfolio.total_value
            if position_size_pct > self.risk_limits["max_position_size"]:
                violations.append(f"Position {position.symbol} size {position_size_pct:.1%} exceeds limit {self.risk_limits['max_position_size']:.1%}")

        return {
            "within_limits": len(violations) == 0,
            "violations": violations,
            "portfolio_heat": portfolio_risk.portfolio_heat,
            "max_drawdown": portfolio_risk.max_drawdown
        }

    async def validate_trade(self, symbol: str, side: str, proposed_size: float,
                           entry_price: float, stop_loss: Optional[float] = None) -> Dict[str, Any]:
        """
        Validate a proposed trade against risk limits.

        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            proposed_size: Proposed position size (0-1 portfolio fraction)
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            Validation result with approval status and adjustments
        """
        if not self._initialized or not self.portfolio:
            return {
                "approved": False,
                "reason": "Risk manager not initialized",
                "adjusted_size": 0.0
            }

        result = {
            "approved": True,
            "reason": "Trade approved",
            "adjusted_size": proposed_size,
            "warnings": [],
            "stop_loss_required": stop_loss is None
        }

        # Check portfolio risk
        risk_assessment = await self.assess_portfolio_risk()
        if not risk_assessment.can_trade:
            result["approved"] = False
            result["reason"] = f"Trading not allowed: {risk_assessment.overall_risk_level} risk level"
            return result

        # Check position size limits
        max_allowed_size = risk_assessment.max_position_size
        if proposed_size > max_allowed_size:
            result["adjusted_size"] = max_allowed_size
            result["warnings"].append(f"Position size reduced from {proposed_size:.3f} to {max_allowed_size:.3f}")

        # Check if we already have a position in this symbol
        if symbol in self.portfolio.positions:
            existing_position = self.portfolio.positions[symbol]
            if existing_position.side != side:
                result["warnings"].append(f"Existing {existing_position.side} position in {symbol} - potential conflict")
            else:
                result["warnings"].append(f"Additional {side} position in {symbol} - increasing exposure")

        # Validate stop loss
        if stop_loss is None:
            # Calculate suggested stop loss based on risk limits
            max_risk_dollars = self.portfolio.total_value * self.risk_limits["max_portfolio_risk"]
            position_size_dollars = proposed_size * self.portfolio.total_value
            position_size_units = (
                position_size_dollars / entry_price if entry_price > 0 else 0.0
            )

            if position_size_units <= 0:
                result["approved"] = False
                result["reason"] = "Invalid position size/entry price for stop loss calculation"
                return result
            
            # Calculate stop loss distance that would result in max risk
            max_risk_per_unit = max_risk_dollars / position_size_units
            
            if side == 'long':
                suggested_sl = entry_price - max_risk_per_unit
            else:
                suggested_sl = entry_price + max_risk_per_unit

            result["suggested_stop_loss"] = suggested_sl
            result["warnings"].append("Stop loss recommended for risk management")
        else:
            # Validate stop loss distance
            # Calculate position size in dollars
            position_size_dollars = proposed_size * self.portfolio.total_value
            # Calculate risk amount (price difference * position size in base currency)
            # For simplicity, assume position size is already in base currency units
            position_size_units = (
                position_size_dollars / entry_price if entry_price > 0 else 0.0
            )
            if position_size_units <= 0:
                result["approved"] = False
                result["reason"] = "Invalid position size/entry price for risk validation"
                return result
            risk_amount = abs(entry_price - stop_loss) * position_size_units
            max_risk = self.portfolio.total_value * self.risk_limits["max_portfolio_risk"]

            if risk_amount > max_risk:
                result["approved"] = False
                result["reason"] = f"Stop loss risk ${risk_amount:.2f} exceeds maximum allowed risk ${max_risk:.2f}"
                return result

        # Check diversification (simple version)
        if len(self.portfolio.positions) >= 3:
            result["warnings"].append("Portfolio becoming concentrated - consider diversification")

        # Final approval
        if result["approved"]:
            logger.info("trade_validated",
                       symbol=symbol,
                       side=side,
                       size=result["adjusted_size"],
                       warnings=len(result["warnings"]))

        return result

    async def calculate_portfolio_optimal_allocation(self, available_symbols: List[str],
                                                   predictions: Dict[str, float]) -> Dict[str, float]:
        """
        Calculate optimal portfolio allocation using modern portfolio theory concepts.

        Args:
            available_symbols: List of tradable symbols
            predictions: Symbol -> prediction strength mapping

        Returns:
            Symbol -> allocation fraction mapping
        """
        if not predictions:
            return {}

        # Filter to symbols with predictions
        valid_symbols = [s for s in available_symbols if s in predictions]

        if not valid_symbols:
            return {}

        # Simple allocation based on prediction strength and diversification
        total_strength = sum(abs(predictions.get(s, 0)) for s in valid_symbols)

        if total_strength == 0:
            # Equal allocation if no strong predictions
            allocation = {s: 1.0 / len(valid_symbols) for s in valid_symbols}
        else:
            # Allocate proportional to prediction strength
            allocation = {}
            for symbol in valid_symbols:
                strength = abs(predictions.get(symbol, 0))
                allocation[symbol] = strength / total_strength

        # Apply risk-adjusted scaling
        risk_assessment = await self.assess_portfolio_risk()
        risk_multiplier = 1.0

        if risk_assessment.overall_risk_level == "high":
            risk_multiplier = 0.6
        elif risk_assessment.overall_risk_level == "critical":
            risk_multiplier = 0.3

        # Scale allocations
        allocation = {s: alloc * risk_multiplier for s, alloc in allocation.items()}

        # Ensure we don't exceed position limits
        max_positions = max(
            0,
            min(
                self.risk_limits["max_open_positions"] - len(self.portfolio.positions),
                len(allocation),
            ),
        )

        if max_positions == 0:
            logger.info(
                "portfolio_allocation_calculated",
                symbols=[],
                allocations=[],
                risk_multiplier=risk_multiplier,
            )
            return {}

        if len(allocation) > max_positions:
            # Keep only top allocations
            sorted_allocs = sorted(allocation.items(), key=lambda x: x[1], reverse=True)
            allocation = dict(sorted_allocs[:max_positions])

            # Renormalize
            total = sum(allocation.values())
            if total > 0:
                allocation = {s: alloc / total for s, alloc in allocation.items()}

        logger.info("portfolio_allocation_calculated",
                   symbols=list(allocation.keys()),
                   allocations=list(allocation.values()),
                   risk_multiplier=risk_multiplier)

        return allocation

    async def update_portfolio_state(self, symbol: str, price_update: float):
        """Update portfolio with latest price information."""
        if self.portfolio:
            self.portfolio.update_position_price(symbol, price_update)

    async def record_completed_trade(self, trade_details: Dict[str, Any]):
        """Record a completed trade for risk analysis."""
        if self.portfolio:
            self.portfolio.record_trade(trade_details)

            logger.info("trade_recorded_for_risk",
                       symbol=trade_details.get("symbol"),
                       pnl=trade_details.get("pnl"),
                       portfolio_value=self.portfolio.total_value)

    def update_risk_limits(self, new_limits: Dict[str, Any]):
        """Update risk management limits."""
        self.risk_limits.update(new_limits)
        logger.info("risk_limits_updated", new_limits=new_limits)

    async def get_risk_report(self) -> Dict[str, Any]:
        """Generate comprehensive risk report."""
        if not self.portfolio:
            return {"error": "Portfolio not initialized"}

        risk_assessment = await self.assess_portfolio_risk()

        report = {
            "portfolio_summary": {
                "total_value": self.portfolio.total_value,
                "cash_balance": self.portfolio.cash_balance,
                "total_exposure": self.portfolio.total_exposure,
                "leverage_ratio": self.portfolio.leverage_ratio,
                "open_positions": len(self.portfolio.positions),
                "peak_value": self.portfolio.peak_portfolio_value,
                "current_drawdown": self.portfolio.get_drawdown()
            },
            "risk_assessment": risk_assessment.to_dict(),
            "performance_metrics": {
                "sharpe_ratio": self.portfolio.get_sharpe_ratio(),
                "total_trades": len(self.portfolio.trade_history),
                "win_rate": self._calculate_win_rate()
            },
            "risk_limits": self.risk_limits.copy(),
            "positions": [pos.to_dict() for pos in self.portfolio.positions.values()],
            "recommendations": risk_assessment.recommendations,
            "emergency_actions": risk_assessment.emergency_actions
        }

        return report

    def _calculate_win_rate(self) -> float:
        """Calculate win rate from trade history."""
        if not self.portfolio or not self.portfolio.trade_history:
            return 0.0

        winning_trades = sum(1 for trade in self.portfolio.trade_history
                           if trade.get("pnl", 0) > 0)
        return winning_trades / len(self.portfolio.trade_history)

    async def get_health_status(self) -> Dict[str, Any]:
        """Get risk manager health status."""
        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "initialized": self._initialized,
            "portfolio_initialized": self.portfolio is not None,
            "risk_limits_configured": bool(self.risk_limits),
            "volatility_adjustments_configured": bool(self.volatility_adjustments),
            "total_positions": len(self.portfolio.positions) if self.portfolio else 0,
            "total_trades": len(self.portfolio.trade_history) if self.portfolio else 0
        }