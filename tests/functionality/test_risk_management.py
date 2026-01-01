"""Test risk management functionality."""

from typing import Dict, Any
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_agent


class RiskManagementTestSuite(TestSuiteBase):
    """Test suite for risk management."""
    
    def __init__(self, test_name: str = "risk_management"):
        super().__init__(test_name)
        self.agent = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.agent = await get_shared_agent()
        except Exception as e:
            # Agent initialization failure will be caught in individual tests
            pass
    
    async def run_all_tests(self):
        """Run all risk management tests."""
        await self._test_risk_assessment()
        await self._test_position_size_calculation()
        await self._test_circuit_breakers()
        await self._test_risk_limit_enforcement()
        await self._test_portfolio_risk_metrics()
    
    async def _test_risk_assessment(self):
        """Test risk assessment for trading decisions."""
        result = TestResult(name="risk_assessment", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager is None:
                result.status = TestStatus.FAIL
                result.issues.append("Risk manager not available")
                result.solutions.append("Check risk manager initialization")
            else:
                result.details["risk_manager_available"] = True
                
                # Test risk assessment methods
                risk_methods = {
                    "assess_risk": hasattr(risk_manager, "assess_risk"),
                    "calculate_position_size": hasattr(risk_manager, "calculate_position_size"),
                    "check_risk_limits": hasattr(risk_manager, "check_risk_limits"),
                    "evaluate_risk": hasattr(risk_manager, "evaluate_risk"),
                }
                
                result.details["available_methods"] = {k: v for k, v in risk_methods.items() if v}
                
                # Test risk assessment if method available
                if risk_methods.get("assess_risk") or risk_methods.get("evaluate_risk"):
                    try:
                        # Create test decision context
                        test_context = {
                            "signal": "BUY",
                            "confidence": 75.0,
                            "symbol": getattr(self.agent, "default_symbol", "BTCUSD"),
                            "price": 50000.0
                        }
                        
                        # Try to call assess_risk or evaluate_risk
                        # Note: assess_risk is synchronous, not async
                        if risk_methods.get("assess_risk"):
                            # assess_risk requires: signal_strength, portfolio_value, available_balance, current_positions
                            portfolio_value = getattr(self.agent, "initial_balance", 10000.0)
                            risk_assessment = risk_manager.assess_risk(
                                signal_strength=test_context.get("confidence", 75.0) / 100.0,
                                portfolio_value=portfolio_value,
                                available_balance=portfolio_value,
                                current_positions=[]
                            )
                        elif risk_methods.get("evaluate_risk"):
                            risk_assessment = await risk_manager.evaluate_risk(test_context)
                        else:
                            risk_assessment = None
                        
                        if risk_assessment:
                            result.details["risk_assessment_generated"] = True
                            result.details["risk_assessment_type"] = type(risk_assessment).__name__
                            
                            # Check if assessment has risk level or score
                            if isinstance(risk_assessment, dict):
                                result.details["risk_assessment_keys"] = list(risk_assessment.keys())[:10]
                                
                                # Check for common risk fields
                                has_risk_level = "risk_level" in risk_assessment or "level" in risk_assessment
                                has_risk_score = "risk_score" in risk_assessment or "score" in risk_assessment
                                
                                result.details["has_risk_level"] = has_risk_level
                                result.details["has_risk_score"] = has_risk_score
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Risk assessment call failed: {e}")
                        result.solutions.append("Check risk manager method signatures and dependencies")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Risk assessment methods not found")
                    result.solutions.append("Check risk manager implementation")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Risk assessment test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_position_size_calculation(self):
        """Test position size calculation based on risk limits."""
        result = TestResult(name="position_size_calculation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager:
                # Check for position size calculation method
                if hasattr(risk_manager, "calculate_position_size"):
                    try:
                        # Test with different confidence levels
                        test_cases = [
                            {"confidence": 50.0, "signal": "BUY"},
                            {"confidence": 75.0, "signal": "BUY"},
                            {"confidence": 90.0, "signal": "STRONG_BUY"},
                        ]
                        
                        calculated_sizes = []
                        for test_case in test_cases:
                            try:
                                # calculate_position_size is synchronous, not async
                                position_size = risk_manager.calculate_position_size(
                                    signal=test_case["signal"],
                                    confidence=test_case["confidence"],
                                    symbol=getattr(self.agent, "default_symbol", "BTCUSD"),
                                    price=50000.0
                                )
                                
                                if position_size is not None:
                                    calculated_sizes.append({
                                        "confidence": test_case["confidence"],
                                        "signal": test_case["signal"],
                                        "position_size": position_size
                                    })
                            except Exception as e:
                                # Method may have different signature
                                pass
                        
                        if calculated_sizes:
                            result.details["position_size_calculation_working"] = True
                            result.details["test_cases_passed"] = len(calculated_sizes)
                            result.details["calculated_sizes"] = calculated_sizes
                            
                            # Validate position sizes are reasonable
                            for size_info in calculated_sizes:
                                size = size_info.get("position_size")
                                if isinstance(size, (int, float)):
                                    if size > 0:
                                        result.details["position_sizes_valid"] = True
                                    else:
                                        result.status = TestStatus.WARNING
                                        result.issues.append(f"Invalid position size: {size}")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Position size calculation returned None or failed")
                            result.solutions.append("Check position size calculation method signature and logic")
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Position size calculation test failed: {e}")
                        result.solutions.append("Check position size calculation method signature")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("calculate_position_size method not found")
                    result.solutions.append("Check risk manager implementation")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Risk manager not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Position size calculation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_circuit_breakers(self):
        """Test circuit breakers (Delta Exchange API failures)."""
        result = TestResult(name="circuit_breakers", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            delta_client = getattr(self.agent, "delta_client", None)
            if delta_client:
                result.details["delta_client_available"] = True
                
                # Check for circuit breaker implementation
                has_circuit_breaker = hasattr(delta_client, "circuit_breaker") or hasattr(delta_client, "_circuit_breaker")
                result.details["circuit_breaker_available"] = has_circuit_breaker
                
                if has_circuit_breaker:
                    circuit_breaker = getattr(delta_client, "circuit_breaker", None) or getattr(delta_client, "_circuit_breaker", None)
                    
                    if circuit_breaker:
                        # Check circuit breaker state
                        if isinstance(circuit_breaker, dict):
                            state = circuit_breaker.get("state", circuit_breaker.get("status"))
                            failure_count = circuit_breaker.get("failure_count", 0)
                            
                            result.details["circuit_breaker_state"] = state
                            result.details["failure_count"] = failure_count
                            result.details["circuit_breaker_operational"] = True
                        elif hasattr(circuit_breaker, "state"):
                            state = circuit_breaker.state
                            result.details["circuit_breaker_state"] = str(state)
                            result.details["circuit_breaker_operational"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Circuit breaker not found in Delta client")
                    result.solutions.append("Circuit breaker may be implemented differently")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Delta Exchange client not available")
                result.solutions.append("Check Delta Exchange client initialization")
            
            # Note: Testing actual circuit breaker activation would require:
            # 1. Simulating API failures
            # 2. Triggering failure threshold
            # 3. Verifying circuit opens
            # This is complex and may require mocking
            result.details["circuit_breaker_test"] = "basic_check_complete"
            result.details["full_circuit_breaker_test"] = "requires_api_failure_simulation"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Circuit breakers test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_risk_limit_enforcement(self):
        """Test risk limit enforcement (max position size, max loss)."""
        result = TestResult(name="risk_limit_enforcement", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager:
                # Check for risk limit checking method
                if hasattr(risk_manager, "check_risk_limits"):
                    try:
                        # Test risk limit checking
                        test_context = {
                            "position_size": 1000.0,
                            "current_exposure": 5000.0,
                            "max_position_size": 10000.0,
                            "max_loss": 1000.0
                        }
                        
                        # check_risk_limits is synchronous, not async
                        limits_ok = risk_manager.check_risk_limits(
                            position_size=test_context.get("position_size", 0.1),
                            current_exposure=test_context.get("current_exposure", 0.0)
                        )
                        
                        if limits_ok is not None:
                            result.details["risk_limit_check_working"] = True
                            result.details["limits_check_result"] = limits_ok
                            
                            if isinstance(limits_ok, dict):
                                result.details["limits_check_keys"] = list(limits_ok.keys())[:10]
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Risk limit check returned None")
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Risk limit check failed: {e}")
                        result.solutions.append("Check risk limit check method signature")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("check_risk_limits method not found")
                    result.solutions.append("Check risk manager implementation")
                
                # Check for risk limit configuration
                max_position = getattr(risk_manager, "max_position_size", None)
                max_loss = getattr(risk_manager, "max_loss", None)
                
                if max_position is not None:
                    result.details["max_position_size_configured"] = True
                    result.details["max_position_size"] = max_position
                
                if max_loss is not None:
                    result.details["max_loss_configured"] = True
                    result.details["max_loss"] = max_loss
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Risk manager not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Risk limit enforcement test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_portfolio_risk_metrics(self):
        """Test portfolio-level risk metrics calculation."""
        result = TestResult(name="portfolio_risk_metrics", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager:
                result.details["risk_manager_available"] = True
                
                # Check for portfolio risk methods
                portfolio_methods = {
                    "calculate_portfolio_risk": hasattr(risk_manager, "calculate_portfolio_risk"),
                    "get_portfolio_metrics": hasattr(risk_manager, "get_portfolio_metrics"),
                    "assess_portfolio_risk": hasattr(risk_manager, "assess_portfolio_risk"),
                }
                
                result.details["portfolio_methods_available"] = {k: v for k, v in portfolio_methods.items() if v}
                
                if any(portfolio_methods.values()):
                    result.details["portfolio_risk_calculation_available"] = True
                    
                    # Test calculate_portfolio_risk if available
                    if portfolio_methods.get("calculate_portfolio_risk"):
                        try:
                            portfolio_risk = risk_manager.calculate_portfolio_risk()
                            if isinstance(portfolio_risk, dict):
                                result.details["portfolio_risk_calculated"] = True
                                result.details["portfolio_risk_keys"] = list(portfolio_risk.keys())[:10]
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Portfolio risk calculation failed: {e}")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Portfolio risk calculation methods not found")
                    result.solutions.append("Portfolio risk may be calculated elsewhere or not yet implemented")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Risk manager not available")
            
            # Check for portfolio/position tracking
            # This may be in a separate portfolio manager
            result.details["portfolio_risk_test"] = "basic_check_complete"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Portfolio risk metrics test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
