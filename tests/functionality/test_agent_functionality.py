"""Comprehensive test suite for agent functionality and working behavior."""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import (
    get_shared_agent, get_shared_backend, check_services_health
)
from tests.functionality.config import config


class AgentFunctionalityTestSuite(TestSuiteBase):
    """Comprehensive test suite for agent functionality."""
    
    def __init__(self, test_name: str = "agent_functionality"):
        super().__init__(test_name)
        self.agent = None
        self.backend_client = None
    
    async def setup(self):
        """Setup shared resources."""
        # Check service health first
        health = await check_services_health()
        backend_health = health.get("backend", {})
        
        if backend_health.get("status") != "up":
            self.add_result(TestResult(
                name="service_health_check",
                status=TestStatus.WARNING,
                duration_ms=0.0,
                issues=["Backend service may not be available"],
                solutions=["Ensure backend is running on http://localhost:8000"]
            ))
        
        # Get shared agent instance
        try:
            self.agent = await get_shared_agent()
        except Exception as e:
            self.add_result(TestResult(
                name="agent_setup",
                status=TestStatus.FAIL,
                duration_ms=0.0,
                error=str(e),
                issues=[f"Failed to initialize agent: {e}"],
                solutions=["Check agent dependencies and configuration"]
            ))
        
        # Get backend client
        try:
            self.backend_client = await get_shared_backend()
        except Exception as e:
            # Backend client failure is not critical for all tests
            pass
    
    async def run_all_tests(self):
        """Run all agent functionality tests."""
        # Core functionality tests
        await self._test_agent_initialization()
        await self._test_agent_state_machine()
        await self._test_agent_decision_making()
        await self._test_agent_signal_generation()
        await self._test_agent_model_integration()
        await self._test_agent_feature_computation()
        await self._test_agent_reasoning_chain()
        await self._test_agent_risk_management()
        await self._test_agent_backend_communication()
        await self._test_agent_health_status()
        await self._test_agent_trading_logic()
        await self._test_agent_event_publishing()
    
    async def _test_agent_initialization(self):
        """Test agent initialization and component setup."""
        result = TestResult(name="agent_initialization", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.FAIL
                result.issues.append("Agent instance is None")
                result.solutions.append("Check agent initialization in setup()")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Check core components
            components = {
                "state_machine": getattr(self.agent, "state_machine", None),
                "mcp_orchestrator": getattr(self.agent, "mcp_orchestrator", None),
                "model_registry": getattr(self.agent, "model_registry", None),
                "risk_manager": getattr(self.agent, "risk_manager", None),
                "delta_client": getattr(self.agent, "delta_client", None),
                "learning_system": getattr(self.agent, "learning_system", None),
                "feature_server_api": getattr(self.agent, "feature_server_api", None),
            }
            
            missing_components = [name for name, component in components.items() if component is None]
            
            if missing_components:
                result.status = TestStatus.FAIL
                result.issues.append(f"Missing components: {', '.join(missing_components)}")
                result.solutions.append("Check agent initialization sequence")
            else:
                result.details["all_components_initialized"] = True
                result.details["component_count"] = len(components)
                
                # Check state machine state
                state_machine = components["state_machine"]
                if state_machine:
                    current_state = getattr(state_machine, "current_state", None)
                    result.details["current_state"] = str(current_state) if current_state else None
                
                # Check model registry
                model_registry = components["model_registry"]
                if model_registry and hasattr(model_registry, "list_models"):
                    models = model_registry.list_models()
                    result.details["registered_models"] = len(models)
                    result.details["model_names"] = models[:5]  # First 5 models
                
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent initialization test failed: {e}")
            result.solutions.append("Check agent dependencies and configuration")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_state_machine(self):
        """Test agent state machine functionality."""
        result = TestResult(name="agent_state_machine", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            state_machine = getattr(self.agent, "state_machine", None)
            if state_machine is None:
                result.status = TestStatus.FAIL
                result.issues.append("State machine not initialized")
                result.solutions.append("Check state machine initialization")
            else:
                # Get current state
                current_state = getattr(state_machine, "current_state", None)
                result.details["current_state"] = str(current_state) if current_state else None
                
                # Check if state machine has transitions
                transitions = getattr(state_machine, "transitions", None)
                if transitions:
                    result.details["transition_count"] = len(transitions)
                    result.details["state_machine_operational"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("State machine has no transitions configured")
                
                # Check context manager
                context_manager = getattr(state_machine, "context_manager", None)
                if context_manager:
                    context = getattr(context_manager, "get_context", None)
                    if context:
                        try:
                            ctx = context()
                            result.details["context_available"] = True
                            result.details["context_keys"] = list(ctx.keys())[:10] if isinstance(ctx, dict) else []
                        except Exception:
                            pass
                
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"State machine test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_decision_making(self):
        """Test agent decision-making process."""
        result = TestResult(name="agent_decision_making", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP orchestrator not available")
                result.solutions.append("Check MCP orchestrator initialization")
            else:
                # Test decision-making with default symbol
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                try:
                    # Call get_trading_decision
                    decision = await mcp_orchestrator.get_trading_decision(
                        symbol=symbol,
                        market_context={}
                    )
                    
                    if decision:
                        result.details["decision_generated"] = True
                        result.details["decision_keys"] = list(decision.keys()) if isinstance(decision, dict) else []
                        
                        # Check for key decision fields
                        if isinstance(decision, dict):
                            signal = decision.get("signal")
                            confidence = decision.get("confidence")
                            reasoning_chain = decision.get("reasoning_chain")
                            
                            result.details["signal"] = signal
                            result.details["confidence"] = confidence
                            result.details["has_reasoning_chain"] = reasoning_chain is not None
                            
                            # Validate signal
                            valid_signals = ["BUY", "SELL", "STRONG_BUY", "STRONG_SELL", "HOLD"]
                            if signal and signal in valid_signals:
                                result.details["signal_valid"] = True
                            elif signal:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Unexpected signal value: {signal}")
                            
                            # Validate confidence
                            if confidence is not None:
                                if 0 <= confidence <= 100:
                                    result.details["confidence_valid"] = True
                                else:
                                    result.status = TestStatus.WARNING
                                    result.issues.append(f"Confidence out of range: {confidence}")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Decision is not a dictionary")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Decision generation returned None")
                        result.solutions.append("Check decision-making logic and dependencies")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Decision-making test failed: {e}")
                    result.solutions.append("Check market data availability and model status")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent decision-making test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_signal_generation(self):
        """Test agent signal generation."""
        result = TestResult(name="agent_signal_generation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Test signal generation via decision-making
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                try:
                    decision = await mcp_orchestrator.get_trading_decision(symbol=symbol)
                    
                    if decision and isinstance(decision, dict):
                        signal = decision.get("signal")
                        confidence = decision.get("confidence")
                        
                        if signal:
                            result.details["signal_generated"] = True
                            result.details["signal"] = signal
                            result.details["confidence"] = confidence
                            
                            # Check signal strength
                            strong_signals = ["STRONG_BUY", "STRONG_SELL"]
                            if signal in strong_signals:
                                result.details["signal_strength"] = "strong"
                            elif signal in ["BUY", "SELL"]:
                                result.details["signal_strength"] = "moderate"
                            elif signal == "HOLD":
                                result.details["signal_strength"] = "neutral"
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("No signal in decision")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Decision not generated or invalid format")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Signal generation test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent signal generation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_model_integration(self):
        """Test agent ML model integration."""
        result = TestResult(name="agent_model_integration", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            model_registry = getattr(self.agent, "model_registry", None)
            if model_registry is None:
                result.status = TestStatus.FAIL
                result.issues.append("Model registry not available")
            else:
                # Check models
                if hasattr(model_registry, "list_models"):
                    models = model_registry.list_models()
                    result.details["model_count"] = len(models)
                    
                    if len(models) > 0:
                        result.details["models_available"] = True
                        result.details["model_names"] = models[:10]  # First 10
                        
                        # Try to get model predictions
                        mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
                        if mcp_orchestrator:
                            try:
                                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                                decision = await mcp_orchestrator.get_trading_decision(symbol=symbol)
                                
                                if decision and isinstance(decision, dict):
                                    model_predictions = decision.get("model_predictions")
                                    if model_predictions:
                                        result.details["predictions_available"] = True
                                        result.details["prediction_count"] = len(model_predictions) if isinstance(model_predictions, (list, dict)) else 0
                                    else:
                                        result.status = TestStatus.WARNING
                                        result.issues.append("No model predictions in decision")
                            except Exception as e:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Model prediction test failed: {e}")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("No models registered")
                        result.solutions.append("Check model discovery and registration")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Model registry missing list_models method")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Model integration test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_feature_computation(self):
        """Test agent feature computation."""
        result = TestResult(name="agent_feature_computation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP orchestrator not available")
            else:
                feature_server = getattr(mcp_orchestrator, "feature_server", None)
                if feature_server is None:
                    result.status = TestStatus.FAIL
                    result.issues.append("Feature server not available")
                else:
                    # Test feature computation
                    symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                    test_features = ["sma_20", "rsi_14", "macd"]
                    
                    try:
                        feature_response = await mcp_orchestrator.get_features(
                            feature_names=test_features,
                            symbol=symbol
                        )
                        
                        if feature_response:
                            features = getattr(feature_response, "features", [])
                            result.details["features_computed"] = len(features)
                            result.details["requested_features"] = len(test_features)
                            
                            if len(features) > 0:
                                result.details["feature_computation_working"] = True
                                
                                # Check feature values
                                valid_features = [f for f in features if hasattr(f, "value") and f.value is not None]
                                result.details["valid_features"] = len(valid_features)
                                
                                if len(valid_features) < len(test_features):
                                    result.status = TestStatus.WARNING
                                    result.issues.append(f"Only {len(valid_features)}/{len(test_features)} features computed")
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append("No features computed")
                                result.solutions.append("Check market data availability and feature computation logic")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Feature computation returned None")
                    
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Feature computation test failed: {e}")
                        result.solutions.append("Check market data service and feature server configuration")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent feature computation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_reasoning_chain(self):
        """Test agent reasoning chain generation."""
        result = TestResult(name="agent_reasoning_chain", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP orchestrator not available")
            else:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine is None:
                    result.status = TestStatus.FAIL
                    result.issues.append("Reasoning engine not available")
                else:
                    # Test reasoning chain generation
                    symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                    
                    try:
                        # Get market context
                        market_context = {}
                        
                        # Generate reasoning chain
                        reasoning_chain = await mcp_orchestrator.generate_reasoning(
                            symbol=symbol,
                            market_context=market_context,
                            use_memory=True
                        )
                        
                        if reasoning_chain:
                            result.details["reasoning_chain_generated"] = True
                            
                            # Check reasoning steps
                            steps = getattr(reasoning_chain, "steps", [])
                            result.details["reasoning_steps"] = len(steps)
                            
                            # Check for 6-step reasoning chain
                            if len(steps) == 6:
                                result.details["complete_reasoning_chain"] = True
                                step_names = [getattr(step, "step_name", "unknown") for step in steps]
                                result.details["step_names"] = step_names
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Expected 6 reasoning steps, got {len(steps)}")
                            
                            # Check final confidence
                            final_confidence = getattr(reasoning_chain, "final_confidence", None)
                            if final_confidence is not None:
                                result.details["final_confidence"] = final_confidence
                                result.details["has_confidence"] = True
                            
                            # Check final signal
                            final_signal = getattr(reasoning_chain, "final_signal", None)
                            if final_signal:
                                result.details["final_signal"] = final_signal
                                result.details["has_signal"] = True
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Reasoning chain generation returned None")
                    
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Reasoning chain test failed: {e}")
                        result.solutions.append("Check reasoning engine dependencies and configuration")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent reasoning chain test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_risk_management(self):
        """Test agent risk management."""
        result = TestResult(name="agent_risk_management", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            risk_manager = getattr(self.agent, "risk_manager", None)
            if risk_manager is None:
                result.status = TestStatus.FAIL
                result.issues.append("Risk manager not available")
            else:
                result.details["risk_manager_available"] = True
                
                # Check risk manager methods
                risk_methods = ["calculate_position_size", "check_risk_limits", "assess_risk"]
                available_methods = [method for method in risk_methods if hasattr(risk_manager, method)]
                result.details["available_risk_methods"] = available_methods
                
                if len(available_methods) > 0:
                    result.details["risk_management_functional"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Risk manager missing expected methods")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Risk management test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_backend_communication(self):
        """Test agent-backend communication."""
        result = TestResult(name="agent_backend_communication", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.backend_client is None:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
                result.solutions.append("Backend may not be running")
            else:
                # Test backend health endpoint
                try:
                    async with self.backend_client.get("/api/v1/health") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result.details["backend_health_ok"] = True
                            
                            # Check agent status in health response
                            services = data.get("services", {})
                            agent_status = services.get("agent", {})
                            if agent_status:
                                agent_available = agent_status.get("status") == "up"
                                result.details["agent_status_in_backend"] = agent_status.get("status")
                                result.details["agent_available"] = agent_available
                                
                                if not agent_available:
                                    result.status = TestStatus.WARNING
                                    result.issues.append("Agent shows as down in backend health check")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Backend health check returned status {resp.status}")
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Backend communication test failed: {e}")
                    result.solutions.append("Check backend is running and accessible")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent-backend communication test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_health_status(self):
        """Test agent health status reporting."""
        result = TestResult(name="agent_health_status", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Test _handle_get_status method
            if hasattr(self.agent, "_handle_get_status"):
                try:
                    status = await self.agent._handle_get_status()
                    
                    if status and isinstance(status, dict):
                        result.details["status_report_generated"] = True
                        result.details["status_keys"] = list(status.keys())
                        
                        # Check for key status fields
                        available = status.get("available", False)
                        state = status.get("state")
                        health = status.get("health", {})
                        
                        result.details["agent_available"] = available
                        result.details["agent_state"] = state
                        result.details["has_health_info"] = bool(health)
                        
                        if not available:
                            result.status = TestStatus.WARNING
                            result.issues.append("Agent reports as unavailable")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Status report not generated or invalid format")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Health status test failed: {e}")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Agent missing _handle_get_status method")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent health status test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_trading_logic(self):
        """Test agent trading logic and decision execution."""
        result = TestResult(name="agent_trading_logic", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Check trading mode
            trading_mode = getattr(self.agent, "trading_mode", None)
            result.details["trading_mode"] = trading_mode
            
            # Check default symbol
            default_symbol = getattr(self.agent, "default_symbol", None)
            result.details["default_symbol"] = default_symbol
            
            # Check confidence threshold
            confidence_threshold = getattr(self.agent, "confidence_threshold", None)
            result.details["confidence_threshold"] = confidence_threshold
            
            # Test prediction handler
            if hasattr(self.agent, "_handle_predict"):
                try:
                    symbol = default_symbol or "BTCUSD"
                    prediction = await self.agent._handle_predict({"symbol": symbol})
                    
                    if prediction and isinstance(prediction, dict):
                        success = prediction.get("success", False)
                        data = prediction.get("data", {})
                        
                        result.details["prediction_handler_works"] = success
                        result.details["has_prediction_data"] = bool(data)
                        
                        if success and data:
                            signal = data.get("signal")
                            confidence = data.get("confidence")
                            result.details["prediction_signal"] = signal
                            result.details["prediction_confidence"] = confidence
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"Prediction handler test failed: {e}")
            
            # Check Delta client
            delta_client = getattr(self.agent, "delta_client", None)
            if delta_client:
                result.details["delta_client_available"] = True
                has_api_key = hasattr(delta_client, "api_key") and delta_client.api_key
                result.details["has_api_credentials"] = has_api_key
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Delta Exchange client not available")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Trading logic test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_event_publishing(self):
        """Test agent event publishing capabilities."""
        result = TestResult(name="agent_event_publishing", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.SKIPPED
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Check if agent has event publishing capabilities
            # This is typically done through the event bus
            result.details["event_publishing_test"] = "basic_check"
            
            # Check for event bus or similar mechanism
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    # Check if reasoning engine can emit events
                    has_emit = hasattr(reasoning_engine, "_emit_decision_ready_event")
                    result.details["can_emit_events"] = has_emit
                    
                    if has_emit:
                        result.details["event_publishing_available"] = True
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Reasoning engine missing event emission capability")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Event publishing test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup after tests."""
        # Agent cleanup is handled by shared resources
        pass

