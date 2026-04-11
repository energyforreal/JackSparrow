"""
Context Manager - Manage agent state and context persistence.

Handles the persistence and restoration of agent state, configuration,
and operational context across restarts.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json
import os
import asyncio
from pathlib import Path
import structlog

logger = structlog.get_logger()


class AgentState:
    """Represents the complete state of the trading agent."""

    def __init__(self):
        self.agent_id: str = "jack_sparrow_v1"
        self.version: str = "1.0.0"
        self.startup_time: datetime = datetime.utcnow()
        self.last_update: datetime = datetime.utcnow()

        # Operational state
        self.is_active: bool = False
        self.trading_enabled: bool = False
        self.emergency_stop: bool = False

        # Portfolio state
        self.portfolio_value: float = 10000.0  # Starting capital
        self.cash_balance: float = 10000.0
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position details
        self.open_orders: Dict[str, Dict[str, Any]] = {}  # order_id -> order details

        # Performance tracking
        self.total_trades: int = 0
        self.profitable_trades: int = 0
        self.total_pnl: float = 0.0
        self.sharpe_ratio: float = 0.0
        self.max_drawdown: float = 0.0

        # Model state
        self.model_weights: Dict[str, float] = {}
        self.model_performance: Dict[str, Dict[str, Any]] = {}
        self.last_model_update: Optional[datetime] = None

        # Learning state
        self.learning_enabled: bool = True
        self.learning_iterations: int = 0
        self.last_learning_update: Optional[datetime] = None

        # Risk management state
        self.risk_limits: Dict[str, Any] = {
            "max_position_size": 0.1,  # 10% of portfolio
            "max_portfolio_risk": 0.05,  # 5% max loss per trade
            "max_daily_loss": 0.02,  # 2% max daily loss
            "max_open_positions": 5
        }
        self.daily_pnl: float = 0.0
        self.daily_loss_limit_hit: bool = False

        # Market state
        self.watched_symbols: List[str] = ["BTCUSD"]
        self.market_regime: str = "neutral"
        self.volatility_regime: str = "normal"

        # Configuration
        self.config: Dict[str, Any] = {}

        # Latest v15 model edge from the most recent decision (for edge-decay exit)
        self.v15_live_edge: Optional[float] = None
        self.v15_live_edge_ts: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "agent_id": self.agent_id,
            "version": self.version,
            "startup_time": self.startup_time.isoformat(),
            "last_update": self.last_update.isoformat(),
            "is_active": self.is_active,
            "trading_enabled": self.trading_enabled,
            "emergency_stop": self.emergency_stop,
            "portfolio_value": self.portfolio_value,
            "cash_balance": self.cash_balance,
            "positions": self.positions,
            "open_orders": self.open_orders,
            "total_trades": self.total_trades,
            "profitable_trades": self.profitable_trades,
            "total_pnl": self.total_pnl,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "model_weights": self.model_weights,
            "model_performance": self.model_performance,
            "last_model_update": self.last_model_update.isoformat() if self.last_model_update else None,
            "learning_enabled": self.learning_enabled,
            "learning_iterations": self.learning_iterations,
            "last_learning_update": self.last_learning_update.isoformat() if self.last_learning_update else None,
            "risk_limits": self.risk_limits,
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit_hit": self.daily_loss_limit_hit,
            "watched_symbols": self.watched_symbols,
            "market_regime": self.market_regime,
            "volatility_regime": self.volatility_regime,
            "config": self.config,
            "v15_live_edge": self.v15_live_edge,
            "v15_live_edge_ts": self.v15_live_edge_ts,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentState':
        """Create state from dictionary."""
        state = cls()

        # Basic attributes
        state.agent_id = data.get("agent_id", state.agent_id)
        state.version = data.get("version", state.version)
        state.is_active = data.get("is_active", state.is_active)
        state.trading_enabled = data.get("trading_enabled", state.trading_enabled)
        state.emergency_stop = data.get("emergency_stop", state.emergency_stop)

        # Portfolio
        state.portfolio_value = data.get("portfolio_value", state.portfolio_value)
        state.cash_balance = data.get("cash_balance", state.cash_balance)
        state.positions = data.get("positions", state.positions)
        state.open_orders = data.get("open_orders", state.open_orders)

        # Performance
        state.total_trades = data.get("total_trades", state.total_trades)
        state.profitable_trades = data.get("profitable_trades", state.profitable_trades)
        state.total_pnl = data.get("total_pnl", state.total_pnl)
        state.sharpe_ratio = data.get("sharpe_ratio", state.sharpe_ratio)
        state.max_drawdown = data.get("max_drawdown", state.max_drawdown)

        # Model state
        state.model_weights = data.get("model_weights", state.model_weights)
        state.model_performance = data.get("model_performance", state.model_performance)

        # Learning state
        state.learning_enabled = data.get("learning_enabled", state.learning_enabled)
        state.learning_iterations = data.get("learning_iterations", state.learning_iterations)

        # Risk management
        state.risk_limits = data.get("risk_limits", state.risk_limits)
        state.daily_pnl = data.get("daily_pnl", state.daily_pnl)
        state.daily_loss_limit_hit = data.get("daily_loss_limit_hit", state.daily_loss_limit_hit)

        # Market state
        state.watched_symbols = data.get("watched_symbols", state.watched_symbols)
        state.market_regime = data.get("market_regime", state.market_regime)
        state.volatility_regime = data.get("volatility_regime", state.volatility_regime)

        # Configuration
        state.config = data.get("config", state.config)
        state.v15_live_edge = data.get("v15_live_edge", state.v15_live_edge)
        state.v15_live_edge_ts = data.get("v15_live_edge_ts", state.v15_live_edge_ts)

        # Handle datetime fields
        if "startup_time" in data:
            state.startup_time = datetime.fromisoformat(data["startup_time"])
        if "last_update" in data:
            state.last_update = datetime.fromisoformat(data["last_update"])
        if "last_model_update" in data and data["last_model_update"]:
            state.last_model_update = datetime.fromisoformat(data["last_model_update"])
        if "last_learning_update" in data and data["last_learning_update"]:
            state.last_learning_update = datetime.fromisoformat(data["last_learning_update"])

        return state

    def update_performance(self, pnl: float, is_profitable: bool):
        """Update performance metrics."""
        self.total_trades += 1
        self.total_pnl += pnl

        if is_profitable:
            self.profitable_trades += 1

        # Update win rate
        if self.total_trades > 0:
            self.win_rate = self.profitable_trades / self.total_trades

        # Update drawdown (simplified)
        current_value = self.portfolio_value + pnl
        if current_value < self.portfolio_value:
            drawdown = (self.portfolio_value - current_value) / self.portfolio_value
            self.max_drawdown = max(self.max_drawdown, drawdown)

        self.portfolio_value = current_value
        self.last_update = datetime.utcnow()

    def can_trade(self) -> bool:
        """Check if agent is allowed to place trades."""
        return (
            self.is_active and
            self.trading_enabled and
            not self.emergency_stop and
            not self.daily_loss_limit_hit and
            len(self.positions) < self.risk_limits["max_open_positions"]
        )

    def get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status."""
        return {
            "daily_loss_limit_hit": self.daily_loss_limit_hit,
            "open_positions_count": len(self.positions),
            "max_positions_limit": self.risk_limits["max_open_positions"],
            "portfolio_risk_level": self._calculate_portfolio_risk(),
            "emergency_stop": self.emergency_stop
        }

    def _calculate_portfolio_risk(self) -> float:
        """Calculate current portfolio risk level (0-1)."""
        # Simplified risk calculation
        position_count_risk = len(self.positions) / self.risk_limits["max_open_positions"]

        # Daily P&L risk
        daily_loss_limit = self.portfolio_value * self.risk_limits["max_daily_loss"]
        if daily_loss_limit > 0:
            daily_pnl_risk = abs(self.daily_pnl) / daily_loss_limit
        else:
            daily_pnl_risk = 0.0

        return min(1.0, (position_count_risk + daily_pnl_risk) / 2.0)


class ContextManager:
    """
    Manages agent state persistence and context management.

    Handles saving and loading agent state, configuration management,
    and provides context for decision making.
    """

    def __init__(self, state_file: str = "agent_state.json", backup_dir: str = "backups"):
        self.state_file = Path("data") / state_file
        self.backup_dir = Path("data") / backup_dir
        self.current_state: Optional[AgentState] = None
        self.state_lock = asyncio.Lock()
        self.auto_save_interval = 300  # 5 minutes
        self._auto_save_task: Optional[asyncio.Task] = None
        self._initialized = False

        # Ensure directories exist
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self, load_existing: bool = True):
        """Initialize context manager."""
        if load_existing:
            await self.load_state()
        else:
            self.current_state = AgentState()

        self._initialized = True

        # Start auto-save task
        self._auto_save_task = asyncio.create_task(self._auto_save_loop())

        logger.info("context_manager_initialized",
                   state_file=str(self.state_file),
                   has_existing_state=self.current_state is not None)

    async def shutdown(self):
        """Shutdown context manager."""
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass

        # Final save
        await self.save_state()

        self._initialized = False
        logger.info("context_manager_shutdown")

    async def save_state(self) -> bool:
        """
        Save current agent state to disk.

        Returns:
            bool: True if saved successfully
        """
        if not self.current_state:
            logger.warning("context_manager_no_state_to_save")
            return False

        async with self.state_lock:
            try:
                # Create backup of existing state
                if self.state_file.exists():
                    await self._create_backup()

                # Save current state
                state_data = self.current_state.to_dict()
                with open(self.state_file, 'w') as f:
                    json.dump(state_data, f, indent=2, default=str)

                logger.info("agent_state_saved",
                           file=str(self.state_file),
                           portfolio_value=self.current_state.portfolio_value,
                           total_trades=self.current_state.total_trades)

                return True

            except Exception as e:
                logger.error("agent_state_save_failed",
                           file=str(self.state_file),
                           error=str(e))
                return False

    async def load_state(self) -> bool:
        """
        Load agent state from disk.

        Returns:
            bool: True if loaded successfully
        """
        if not self.state_file.exists():
            logger.info("agent_state_file_not_found",
                       file=str(self.state_file),
                       message="Starting with fresh state")
            self.current_state = AgentState()
            return True

        async with self.state_lock:
            try:
                with open(self.state_file, 'r') as f:
                    state_data = json.load(f)

                self.current_state = AgentState.from_dict(state_data)

                # Update startup time for this session
                self.current_state.startup_time = datetime.utcnow()

                # Paper mode: start with fresh portfolio/positions/trades each load
                try:
                    from agent.core.config import settings as agent_settings
                except Exception:
                    agent_settings = None
                if agent_settings and getattr(agent_settings, "paper_trading_mode", True):
                    initial = getattr(agent_settings, "initial_balance", 10000.0)
                    self.current_state.portfolio_value = float(initial)
                    self.current_state.cash_balance = float(initial)
                    self.current_state.positions = {}
                    self.current_state.open_orders = {}
                    self.current_state.total_trades = 0
                    self.current_state.profitable_trades = 0
                    self.current_state.total_pnl = 0.0
                    self.current_state.daily_pnl = 0.0
                    self.current_state.daily_loss_limit_hit = False
                    logger.info(
                        "agent_state_loaded_paper_reset",
                        file=str(self.state_file),
                        initial_balance=initial,
                        message="Paper trading: portfolio/positions/trades reset for new session",
                    )

                logger.info("agent_state_loaded",
                           file=str(self.state_file),
                           portfolio_value=self.current_state.portfolio_value,
                           total_trades=self.current_state.total_trades,
                           last_update=self.current_state.last_update.isoformat())

                return True

            except Exception as e:
                logger.error("agent_state_load_failed",
                           file=str(self.state_file),
                           error=str(e))
                # Start with fresh state on load failure
                self.current_state = AgentState()
                return False

    async def _create_backup(self):
        """Create a backup of the current state file."""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"agent_state_{timestamp}.json"

            # Copy current state file
            import shutil
            shutil.copy2(self.state_file, backup_file)

            # Keep only last 10 backups
            backup_files = sorted(self.backup_dir.glob("agent_state_*.json"))
            if len(backup_files) > 10:
                for old_backup in backup_files[:-10]:
                    old_backup.unlink()

            logger.debug("agent_state_backup_created", backup_file=str(backup_file))

        except Exception as e:
            logger.warning("agent_state_backup_failed", error=str(e))

    async def _auto_save_loop(self):
        """Auto-save state at regular intervals."""
        while self._initialized:
            try:
                await asyncio.sleep(self.auto_save_interval)
                if self.current_state and self._initialized:
                    await self.save_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("auto_save_failed", error=str(e))

    def get_state(self) -> Optional[AgentState]:
        """Get current agent state."""
        return self.current_state

    async def update_state(self, updates: Dict[str, Any]) -> bool:
        """
        Update agent state with new values.

        Args:
            updates: Dictionary of state field updates

        Returns:
            bool: True if updated successfully
        """
        if not self.current_state:
            return False

        async with self.state_lock:
            try:
                for key, value in updates.items():
                    if hasattr(self.current_state, key):
                        setattr(self.current_state, key, value)

                self.current_state.last_update = datetime.utcnow()

                # Auto-save critical updates immediately
                if any(key in updates for key in ["portfolio_value", "emergency_stop", "trading_enabled"]):
                    await self.save_state()

                logger.debug("agent_state_updated", updates=list(updates.keys()))
                return True

            except Exception as e:
                logger.error("agent_state_update_failed", error=str(e))
                return False

    def add_state_transition(self, from_state: str, to_state: str, reason: str) -> None:
        """
        Record a state transition for tracking purposes.

        Args:
            from_state: The state being transitioned from
            to_state: The state being transitioned to
            reason: The reason for the transition
        """
        # This method could be used for logging or analytics
        # For now, we'll just log the transition
        logger.info("state_transition_recorded",
                   from_state=from_state,
                   to_state=to_state,
                   reason=reason)

    async def record_trade(self, trade_details: Dict[str, Any]) -> bool:
        """
        Record a completed trade in the agent state.

        Args:
            trade_details: Trade information including P&L

        Returns:
            bool: True if recorded successfully
        """
        if not self.current_state:
            return False

        pnl = trade_details.get("pnl", 0.0)
        is_profitable = pnl > 0

        # Update state
        updates = {
            "total_trades": self.current_state.total_trades + 1,
            "total_pnl": self.current_state.total_pnl + pnl,
            "daily_pnl": self.current_state.daily_pnl + pnl
        }

        if is_profitable:
            updates["profitable_trades"] = self.current_state.profitable_trades + 1

        # Update portfolio value
        updates["portfolio_value"] = self.current_state.portfolio_value + pnl

        success = await self.update_state(updates)

        if success:
            logger.info("trade_recorded",
                       trade_id=trade_details.get("trade_id"),
                       pnl=pnl,
                       is_profitable=is_profitable,
                       new_portfolio_value=self.current_state.portfolio_value)

        return success

    async def check_risk_limits(self) -> Dict[str, Any]:
        """Check if any risk limits have been breached."""
        if not self.current_state:
            return {"breached": True, "reason": "No state available"}

        breaches = []

        # Daily loss limit
        daily_loss_limit = self.current_state.portfolio_value * self.current_state.risk_limits["max_daily_loss"]
        if self.current_state.daily_pnl < -daily_loss_limit:
            breaches.append({
                "type": "daily_loss_limit",
                "current": self.current_state.daily_pnl,
                "limit": -daily_loss_limit,
                "breached": True
            })

        # Max open positions
        if len(self.current_state.positions) >= self.current_state.risk_limits["max_open_positions"]:
            breaches.append({
                "type": "max_open_positions",
                "current": len(self.current_state.positions),
                "limit": self.current_state.risk_limits["max_open_positions"],
                "breached": True
            })

        # Emergency stop
        if self.current_state.emergency_stop:
            breaches.append({
                "type": "emergency_stop",
                "breached": True
            })

        return {
            "breached": len(breaches) > 0,
            "breaches": breaches,
            "can_trade": len(breaches) == 0 and self.current_state.can_trade()
        }

    async def reset_daily_pnl(self):
        """Reset daily P&L tracking (call at start of each trading day)."""
        await self.update_state({
            "daily_pnl": 0.0,
            "daily_loss_limit_hit": False
        })
        logger.info("daily_pnl_reset")

    async def get_context_snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of current context for decision making."""
        if not self.current_state:
            return {"error": "No state available"}

        return {
            "portfolio_value": self.current_state.portfolio_value,
            "cash_balance": self.current_state.cash_balance,
            "open_positions": len(self.current_state.positions),
            "daily_pnl": self.current_state.daily_pnl,
            "total_trades": self.current_state.total_trades,
            "win_rate": self.current_state.profitable_trades / max(1, self.current_state.total_trades),
            "market_regime": self.current_state.market_regime,
            "volatility_regime": self.current_state.volatility_regime,
            "trading_enabled": self.current_state.trading_enabled,
            "risk_status": self.current_state.get_risk_status(),
            "model_weights": self.current_state.model_weights.copy(),
            "last_update": self.current_state.last_update.isoformat()
        }

    async def export_state(self, export_file: Path) -> bool:
        """Export agent state to a specific file."""
        if not self.current_state:
            return False

        try:
            state_data = self.current_state.to_dict()
            with open(export_file, 'w') as f:
                json.dump(state_data, f, indent=2, default=str)

            logger.info("agent_state_exported", file=str(export_file))
            return True
        except Exception as e:
            logger.error("agent_state_export_failed", file=str(export_file), error=str(e))
            return False

    async def import_state(self, import_file: Path) -> bool:
        """Import agent state from a specific file."""
        if not import_file.exists():
            logger.error("import_file_not_found", file=str(import_file))
            return False

        try:
            with open(import_file, 'r') as f:
                state_data = json.load(f)

            new_state = AgentState.from_dict(state_data)

            # Backup current state before import
            if self.current_state:
                await self._create_backup()

            self.current_state = new_state
            await self.save_state()

            logger.info("agent_state_imported", file=str(import_file))
            return True
        except Exception as e:
            logger.error("agent_state_import_failed", file=str(import_file), error=str(e))
            return False

    async def get_health_status(self) -> Dict[str, Any]:
        """Get context manager health status."""
        state_exists = self.state_file.exists()
        state_size = self.state_file.stat().st_size if state_exists else 0

        backup_files = list(self.backup_dir.glob("agent_state_*.json"))
        backup_count = len(backup_files)

        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "initialized": self._initialized,
            "state_file_exists": state_exists,
            "state_file_size": state_size,
            "backup_count": backup_count,
            "auto_save_active": self._auto_save_task is not None and not self._auto_save_task.done(),
            "current_state_loaded": self.current_state is not None,
            "last_save_time": self.current_state.last_update.isoformat() if self.current_state else None
        }


# Create global context manager instance
context_manager = ContextManager()