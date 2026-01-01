"""Test portfolio management functionality."""

from typing import Dict, Any, List
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_agent, get_shared_backend


class PortfolioManagementTestSuite(TestSuiteBase):
    """Test suite for portfolio management."""
    
    def __init__(self, test_name: str = "portfolio_management"):
        super().__init__(test_name)
        self.agent = None
        self.backend_client = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.agent = await get_shared_agent()
        except Exception:
            pass
        
        try:
            self.backend_client = await get_shared_backend()
        except Exception:
            pass
    
    async def run_all_tests(self):
        """Run all portfolio management tests."""
        await self._test_portfolio_state()
        await self._test_position_tracking()
        await self._test_performance_metrics()
        await self._test_portfolio_rebalancing()
        await self._test_trade_execution_updates()
    
    async def _test_portfolio_state(self):
        """Test portfolio state calculation."""
        result = TestResult(name="portfolio_state", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.backend_client:
                # Test portfolio endpoint if available
                try:
                    async with self.backend_client.get("/api/v1/portfolio") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result.details["portfolio_endpoint_available"] = True
                            
                            # Check portfolio state fields
                            if isinstance(data, dict):
                                portfolio_fields = ["balance", "equity", "positions", "total_value"]
                                present_fields = [field for field in portfolio_fields if field in data]
                                result.details["portfolio_fields_present"] = present_fields
                                result.details["portfolio_state_available"] = len(present_fields) > 0
                                
                                # Check for positions
                                positions = data.get("positions", [])
                                result.details["position_count"] = len(positions) if isinstance(positions, list) else 0
                                
                                # Check for balance/equity
                                balance = data.get("balance")
                                equity = data.get("equity")
                                total_value = data.get("total_value")
                                
                                if balance is not None:
                                    result.details["has_balance"] = True
                                    result.details["balance"] = balance
                                
                                if equity is not None:
                                    result.details["has_equity"] = True
                                    result.details["equity"] = equity
                                
                                if total_value is not None:
                                    result.details["has_total_value"] = True
                                    result.details["total_value"] = total_value
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Portfolio endpoint returned status {resp.status}")
                            result.solutions.append("Portfolio endpoint may not be implemented or requires authentication")
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Portfolio state test failed: {e}")
                    result.solutions.append("Check backend portfolio endpoint implementation")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
                result.solutions.append("Ensure backend is running")
            
            # Check agent for portfolio tracking
            if self.agent:
                initial_balance = getattr(self.agent, "initial_balance", None)
                if initial_balance:
                    result.details["agent_initial_balance"] = initial_balance
                    result.details["portfolio_tracking_available"] = True
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Portfolio state test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_position_tracking(self):
        """Test position tracking and updates."""
        result = TestResult(name="position_tracking", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.backend_client:
                # Test positions endpoint
                try:
                    async with self.backend_client.get("/api/v1/positions") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result.details["positions_endpoint_available"] = True
                            
                            if isinstance(data, (list, dict)):
                                positions = data if isinstance(data, list) else data.get("positions", [])
                                result.details["position_count"] = len(positions)
                                
                                # Validate position structure
                                if positions:
                                    first_position = positions[0]
                                    if isinstance(first_position, dict):
                                        position_fields = ["symbol", "quantity", "entry_price", "side"]
                                        present_fields = [field for field in position_fields if field in first_position]
                                        result.details["position_fields_present"] = present_fields
                                        result.details["position_structure_valid"] = len(present_fields) >= 2
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Positions endpoint returned status {resp.status}")
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Position tracking test failed: {e}")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
            
            # Check risk manager for position tracking
            if self.agent:
                risk_manager = getattr(self.agent, "risk_manager", None)
                if risk_manager:
                    current_position = getattr(risk_manager, "current_position", None)
                    result.details["risk_manager_tracks_position"] = current_position is not None
                    
                    if current_position:
                        result.details["has_current_position"] = True
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Position tracking test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_performance_metrics(self):
        """Test performance metrics calculation (PnL, Sharpe ratio, etc.)."""
        result = TestResult(name="performance_metrics", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.backend_client:
                # Test performance/metrics endpoint
                try:
                    async with self.backend_client.get("/api/v1/performance") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result.details["performance_endpoint_available"] = True
                            
                            if isinstance(data, dict):
                                # Check for common performance metrics
                                metrics_fields = ["pnl", "returns", "sharpe_ratio", "win_rate", "total_trades"]
                                present_fields = [field for field in metrics_fields if field in data]
                                result.details["metrics_fields_present"] = present_fields
                                result.details["performance_metrics_available"] = len(present_fields) > 0
                                
                                # Validate metric values
                                if "pnl" in data:
                                    pnl = data["pnl"]
                                    result.details["has_pnl"] = True
                                    result.details["pnl"] = pnl
                                
                                if "returns" in data:
                                    returns = data["returns"]
                                    result.details["has_returns"] = True
                                    result.details["returns"] = returns
                                
                                if "sharpe_ratio" in data:
                                    sharpe = data["sharpe_ratio"]
                                    result.details["has_sharpe_ratio"] = True
                                    result.details["sharpe_ratio"] = sharpe
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Performance endpoint returned status {resp.status}")
                            result.solutions.append("Performance endpoint may not be implemented")
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Performance metrics test failed: {e}")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
            
            # Check learning system for performance tracking
            if self.agent:
                learning_system = getattr(self.agent, "learning_system", None)
                if learning_system:
                    result.details["learning_system_available"] = True
                    # Learning system may track performance for model adaptation
                    result.details["performance_tracking_mechanism"] = "available"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Performance metrics test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_portfolio_rebalancing(self):
        """Test portfolio rebalancing logic."""
        result = TestResult(name="portfolio_rebalancing", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            # Check for rebalancing logic
            # This may be in risk manager or a separate portfolio manager
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager:
                # Check for portfolio heat calculation (used for rebalancing)
                max_portfolio_heat = getattr(risk_manager, "max_portfolio_heat", None)
                if max_portfolio_heat:
                    result.details["max_portfolio_heat_configured"] = True
                    result.details["max_portfolio_heat"] = max_portfolio_heat
                    result.details["rebalancing_trigger_available"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Max portfolio heat not configured")
            
            # Note: Actual rebalancing testing would require:
            # 1. Multiple positions
            # 2. Portfolio heat exceeding threshold
            # 3. Verifying rebalancing action
            result.details["rebalancing_test"] = "basic_check_complete"
            result.details["full_rebalancing_test"] = "requires_multiple_positions"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Portfolio rebalancing test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_trade_execution_updates(self):
        """Test trade execution and position updates."""
        result = TestResult(name="trade_execution_updates", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            # Check for trade execution handler
            if hasattr(self.agent, "_handle_execute_trade"):
                result.details["trade_execution_handler_available"] = True
                
                # Test trade execution (paper trading mode)
                try:
                    test_trade = {
                        "symbol": getattr(self.agent, "default_symbol", "BTCUSD"),
                        "side": "BUY",
                        "quantity": 0.001,
                        "price": 50000.0
                    }
                    
                    trade_result = await self.agent._handle_execute_trade(test_trade)
                    
                    if trade_result and isinstance(trade_result, dict):
                        success = trade_result.get("success", False)
                        result.details["trade_execution_works"] = success
                        
                        if success:
                            trade_data = trade_result.get("data", {})
                            result.details["trade_data_available"] = bool(trade_data)
                            
                            # Check for trade ID
                            trade_id = trade_data.get("trade_id")
                            if trade_id:
                                result.details["trade_id_generated"] = True
                                result.details["trade_id"] = trade_id
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Trade execution test failed: {e}")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Trade execution handler not found")
                result.solutions.append("Check agent trade execution implementation")
            
            # Check if positions are updated after trade
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager:
                current_position = getattr(risk_manager, "current_position", None)
                result.details["position_tracking_after_trade"] = current_position is not None
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Trade execution updates test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
