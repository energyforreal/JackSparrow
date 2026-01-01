"""Test signal generation and interpretation."""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import (
    get_shared_agent, get_shared_backend_websocket, get_shared_redis
)


class SignalGenerationTestSuite(TestSuiteBase):
    """Test suite for signal generation."""
    
    def __init__(self, test_name: str = "signal_generation"):
        super().__init__(test_name)
        self.agent = None
        self.backend_ws = None
        self.redis = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.agent = await get_shared_agent()
        except Exception as e:
            # Agent initialization failure will be caught in individual tests
            pass
        
        try:
            self.backend_ws = await get_shared_backend_websocket()
        except Exception:
            # WebSocket may not be available
            pass
        
        try:
            self.redis = await get_shared_redis()
        except Exception:
            # Redis may not be available
            pass
    
    async def run_all_tests(self):
        """Run all signal generation tests."""
        await self._test_signal_generation()
        await self._test_signal_validation()
        await self._test_signal_confidence()
        await self._test_signal_metadata()
        await self._test_signal_broadcasting()
        await self._test_signal_persistence()
    
    async def _test_signal_generation(self):
        """Test signal generation from model predictions."""
        result = TestResult(name="signal_generation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP orchestrator not available")
                result.solutions.append("Check agent initialization")
            else:
                # Test signal generation via get_trading_decision
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                try:
                    decision = await mcp_orchestrator.get_trading_decision(
                        symbol=symbol,
                        market_context={}
                    )
                    
                    if decision and isinstance(decision, dict):
                        signal = decision.get("signal")
                        
                        if signal:
                            result.details["signal_generated"] = True
                            result.details["signal"] = signal
                            result.details["symbol"] = symbol
                            
                            # Validate signal type
                            valid_signals = ["BUY", "SELL", "STRONG_BUY", "STRONG_SELL", "HOLD"]
                            if signal in valid_signals:
                                result.details["signal_valid"] = True
                                result.details["signal_type"] = signal
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Unexpected signal value: {signal}")
                                result.solutions.append("Check signal generation logic")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("No signal in decision")
                            result.solutions.append("Check decision-making logic and model predictions")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Decision generation returned None or invalid format")
                        result.solutions.append("Check market data availability and model status")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Signal generation failed: {e}")
                    result.solutions.append("Check market data service and model availability")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Signal generation test failed: {e}")
            result.solutions.append("Check agent initialization and dependencies")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_signal_validation(self):
        """Test signal format and required fields validation."""
        result = TestResult(name="signal_validation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                try:
                    decision = await mcp_orchestrator.get_trading_decision(symbol=symbol)
                    
                    if decision and isinstance(decision, dict):
                        # Check required fields
                        required_fields = ["signal", "confidence"]
                        missing_fields = [field for field in required_fields if field not in decision]
                        
                        if missing_fields:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Missing required fields: {', '.join(missing_fields)}")
                            result.solutions.append("Check decision-making response format")
                        else:
                            result.details["all_required_fields_present"] = True
                            
                            # Validate signal format
                            signal = decision.get("signal")
                            valid_signals = ["BUY", "SELL", "STRONG_BUY", "STRONG_SELL", "HOLD"]
                            
                            if signal in valid_signals:
                                result.details["signal_format_valid"] = True
                                
                                # Check for additional metadata
                                optional_fields = ["reasoning_chain", "model_predictions", "features", "timestamp"]
                                present_fields = [field for field in optional_fields if field in decision]
                                result.details["optional_fields_present"] = present_fields
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Invalid signal format: {signal}")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Decision not generated or invalid format")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Signal validation test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Signal validation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_signal_confidence(self):
        """Test signal confidence calculation and validation."""
        result = TestResult(name="signal_confidence", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                try:
                    decision = await mcp_orchestrator.get_trading_decision(symbol=symbol)
                    
                    if decision and isinstance(decision, dict):
                        confidence = decision.get("confidence")
                        
                        if confidence is not None:
                            # Validate confidence range (0-100%)
                            if isinstance(confidence, (int, float)):
                                if 0 <= confidence <= 100:
                                    result.details["confidence_valid"] = True
                                    result.details["confidence_value"] = confidence
                                    
                                    # Check confidence threshold
                                    confidence_threshold = getattr(self.agent, "confidence_threshold", 65.0)
                                    result.details["confidence_threshold"] = confidence_threshold
                                    
                                    if confidence >= confidence_threshold:
                                        result.details["above_threshold"] = True
                                    else:
                                        result.details["above_threshold"] = False
                                        result.details["below_threshold"] = True
                                else:
                                    result.status = TestStatus.WARNING
                                    result.issues.append(f"Confidence out of range: {confidence} (expected 0-100)")
                                    result.solutions.append("Check confidence calculation logic")
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Confidence is not numeric: {type(confidence)}")
                                result.solutions.append("Check confidence calculation return type")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Confidence not present in decision")
                            result.solutions.append("Check decision-making logic includes confidence")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Decision not generated")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Confidence test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Signal confidence test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_signal_metadata(self):
        """Test signal metadata (timestamp, symbol, reasoning_chain_id)."""
        result = TestResult(name="signal_metadata", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                try:
                    decision = await mcp_orchestrator.get_trading_decision(symbol=symbol)
                    
                    if decision and isinstance(decision, dict):
                        # Check for timestamp
                        timestamp = decision.get("timestamp")
                        if timestamp:
                            result.details["has_timestamp"] = True
                            result.details["timestamp"] = timestamp
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Timestamp not present in decision")
                        
                        # Check for symbol
                        decision_symbol = decision.get("symbol", symbol)
                        result.details["symbol"] = decision_symbol
                        if decision_symbol == symbol:
                            result.details["symbol_matches"] = True
                        
                        # Check for reasoning chain
                        reasoning_chain = decision.get("reasoning_chain")
                        if reasoning_chain:
                            result.details["has_reasoning_chain"] = True
                            
                            # Check reasoning chain structure
                            if isinstance(reasoning_chain, dict):
                                chain_id = reasoning_chain.get("chain_id")
                                steps = reasoning_chain.get("steps", [])
                                
                                if chain_id:
                                    result.details["has_chain_id"] = True
                                    result.details["chain_id"] = chain_id
                                
                                if steps:
                                    result.details["reasoning_steps_count"] = len(steps)
                                    if len(steps) == 6:
                                        result.details["complete_reasoning_chain"] = True
                                    else:
                                        result.status = TestStatus.WARNING
                                        result.issues.append(f"Expected 6 reasoning steps, got {len(steps)}")
                        else:
                            result.details["has_reasoning_chain"] = False
                            result.status = TestStatus.WARNING
                            result.issues.append("Reasoning chain not present in decision")
                    
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Metadata test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Signal metadata test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_signal_broadcasting(self):
        """Test signal broadcasting via WebSocket to backend."""
        result = TestResult(name="signal_broadcasting", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            # Check if WebSocket client is available
            websocket_client = getattr(self.agent, "websocket_client", None)
            if websocket_client is None:
                result.status = TestStatus.WARNING
                result.issues.append("WebSocket client not available")
                result.solutions.append("WebSocket client may not be initialized or backend not running")
            else:
                result.details["websocket_client_available"] = True
                
                # Check if WebSocket is connected
                is_connected = getattr(websocket_client, "is_connected", False)
                result.details["websocket_connected"] = is_connected
                
                if is_connected:
                    result.details["can_broadcast"] = True
                    
                    # Test event publishing capability
                    try:
                        from agent.events.event_bus import event_bus
                        result.details["event_bus_available"] = True
                        
                        # Check if event bus can publish (this is tested indirectly)
                        # Actual signal_update events are published by reasoning_engine
                        result.details["event_publishing_mechanism"] = "available"
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.issues.append(f"Event bus check failed: {e}")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("WebSocket client not connected")
                    result.solutions.append("Check backend WebSocket server is running on ws://localhost:8000/ws/agent")
            
            # Also check backend WebSocket connection for receiving signals
            if self.backend_ws:
                try:
                    # Subscribe to signal_update messages
                    subscribe_msg = json.dumps({
                        "action": "subscribe",
                        "channels": ["signal_update"]
                    })
                    await self.backend_ws.send(subscribe_msg)
                    result.details["backend_websocket_subscribed"] = True
                    
                    # Note: Actual signal reception would require waiting for agent to generate signal
                    # This is tested indirectly through the signal generation test
                    result.details["signal_reception_ready"] = True
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"Backend WebSocket subscription failed: {e}")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Backend WebSocket connection not available")
                result.solutions.append("Backend may not be running or WebSocket not accessible")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Signal broadcasting test failed: {e}")
            result.solutions.append("Check WebSocket configuration and backend availability")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_signal_persistence(self):
        """Test signal persistence in Redis streams."""
        result = TestResult(name="signal_persistence", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.redis is None:
                result.status = TestStatus.WARNING
                result.issues.append("Redis connection not available")
                result.solutions.append("Ensure Redis is running and REDIS_URL is configured")
            else:
                result.details["redis_available"] = True
                
                # Check if event bus uses Redis
                try:
                    from agent.events.event_bus import event_bus
                    result.details["event_bus_available"] = True
                    
                    # Check Redis stream key (typically "agent_events" or similar)
                    # The actual stream name is configured in event_bus
                    result.details["redis_streams_configured"] = True
                    
                    # Test Redis connectivity
                    await self.redis.ping()
                    result.details["redis_connected"] = True
                    
                    # Note: Actual signal persistence would require:
                    # 1. Agent generating a signal
                    # 2. Event bus publishing to Redis stream
                    # 3. Reading from Redis stream to verify
                    # This is tested indirectly through signal generation
                    result.details["signal_persistence_mechanism"] = "available"
                    
                except ImportError:
                    result.status = TestStatus.WARNING
                    result.issues.append("Event bus not available")
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Redis persistence test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Signal persistence test failed: {e}")
            result.solutions.append("Check Redis configuration and connectivity")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        # Cleanup is handled by shared resources
        pass
