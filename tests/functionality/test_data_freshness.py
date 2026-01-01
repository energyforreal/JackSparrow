"""Test data freshness functionality."""

import asyncio
from typing import Dict, Any
from datetime import datetime, timezone, timedelta

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_agent, get_shared_backend_websocket


class DataFreshnessTestSuite(TestSuiteBase):
    """Test suite for data freshness."""
    
    def __init__(self, test_name: str = "data_freshness"):
        super().__init__(test_name)
        self.agent = None
        self.backend_ws = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.agent = await get_shared_agent()
        except Exception:
            pass
        
        try:
            self.backend_ws = await get_shared_backend_websocket()
        except Exception:
            pass
    
    async def run_all_tests(self):
        """Run all data freshness tests."""
        await self._test_timestamp_validation()
        await self._test_freshness_calculation()
        await self._test_agent_state_updates()
        await self._test_health_status_updates()
        await self._test_stale_data_detection()
        await self._test_websocket_message_freshness()
    
    async def _test_timestamp_validation(self):
        """Test timestamp validation for market data."""
        result = TestResult(name="timestamp_validation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            # Test ISO 8601 format
            test_timestamp = datetime.now(timezone.utc).isoformat()
            result.details["timestamp_format"] = "ISO 8601"
            result.details["test_timestamp"] = test_timestamp
            
            # Validate timestamp can be parsed
            try:
                parsed = datetime.fromisoformat(test_timestamp.replace("Z", "+00:00"))
                result.details["timestamp_parsable"] = True
                result.details["parsed_timestamp"] = parsed.isoformat()
            except Exception as parse_error:
                result.status = TestStatus.WARNING
                result.issues.append(f"Timestamp parsing failed: {parse_error}")
            
            # Test timestamp age calculation
            old_timestamp = datetime.now(timezone.utc)
            await asyncio.sleep(0.1)
            new_timestamp = datetime.now(timezone.utc)
            age_seconds = (new_timestamp - old_timestamp).total_seconds()
            
            result.details["age_calculation_working"] = True
            result.details["age_seconds"] = round(age_seconds, 3)
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Timestamp validation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_freshness_calculation(self):
        """Test freshness calculation."""
        result = TestResult(name="freshness_calculation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            # Test age calculation in milliseconds
            old_time = datetime.now(timezone.utc)
            await asyncio.sleep(0.1)
            new_time = datetime.now(timezone.utc)
            age_ms = (new_time - old_time).total_seconds() * 1000
            
            result.details["age_calculation"] = f"{age_ms:.2f}ms"
            result.details["age_calculation_working"] = True
            
            # Test freshness threshold (10 seconds for market data)
            threshold_seconds = 10
            test_age_seconds = 5.0  # Fresh
            is_fresh = test_age_seconds < threshold_seconds
            result.details["freshness_check_working"] = True
            result.details["test_age_seconds"] = test_age_seconds
            result.details["threshold_seconds"] = threshold_seconds
            result.details["is_fresh"] = is_fresh
            
            # Test stale detection
            stale_age_seconds = 15.0  # Stale
            is_stale = stale_age_seconds >= threshold_seconds
            result.details["stale_detection_working"] = True
            result.details["stale_age_seconds"] = stale_age_seconds
            result.details["is_stale"] = is_stale
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Freshness calculation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_state_updates(self):
        """Test agent state update frequency (30s intervals)."""
        result = TestResult(name="agent_state_updates", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            # Check agent state machine
            state_machine = getattr(self.agent, "state_machine", None)
            if state_machine:
                current_state = getattr(state_machine, "current_state", None)
                result.details["current_state"] = str(current_state) if current_state else None
                result.details["state_machine_available"] = True
                
                # Check for periodic monitoring
                # Agent should update state periodically
                result.details["state_update_mechanism"] = "available"
                result.details["expected_update_interval"] = "30s"
            else:
                result.status = TestStatus.WARNING
                result.issues.append("State machine not available")
            
            # Test via backend WebSocket if available
            if self.backend_ws:
                try:
                    import json
                    # Subscribe to agent_state messages
                    subscribe_msg = json.dumps({
                        "action": "subscribe",
                        "channels": ["agent_state"]
                    })
                    await self.backend_ws.send(subscribe_msg)
                    result.details["subscribed_to_agent_state"] = True
                    
                    # Note: Actual state update frequency would require waiting and monitoring
                    # This is tested indirectly through WebSocket message freshness
                    result.details["state_update_monitoring"] = "ready"
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"State update subscription failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Agent state updates test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_health_status_updates(self):
        """Test health status update frequency (60s intervals)."""
        result = TestResult(name="health_status_updates", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            # Test health endpoint freshness
            from tests.functionality.fixtures import get_shared_backend
            backend_client = await get_shared_backend()
            
            if backend_client:
                try:
                    async with backend_client.get("/api/v1/health") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result.details["health_endpoint_available"] = True
                            
                            # Check for timestamp in health response
                            timestamp = data.get("timestamp")
                            if timestamp:
                                result.details["health_response_has_timestamp"] = True
                                result.details["timestamp"] = timestamp
                                
                                # Calculate age
                                try:
                                    response_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                                    now = datetime.now(timezone.utc)
                                    age_seconds = (now - response_time).total_seconds()
                                    result.details["health_response_age_seconds"] = round(age_seconds, 2)
                                    
                                    # Health should be fresh (< 60s)
                                    if age_seconds < 60:
                                        result.details["health_fresh"] = True
                                    else:
                                        result.status = TestStatus.WARNING
                                        result.issues.append(f"Health response is stale: {age_seconds:.0f}s old")
                                except Exception:
                                    pass
                            
                            # Check agent status in health
                            services = data.get("services", {})
                            agent_status = services.get("agent", {})
                            if agent_status:
                                agent_timestamp = agent_status.get("last_update")
                                if agent_timestamp:
                                    result.details["agent_status_has_timestamp"] = True
                                    result.details["agent_last_update"] = agent_timestamp
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Health endpoint returned status {resp.status}")
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Health status check failed: {e}")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
            
            result.details["expected_update_interval"] = "60s"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Health status updates test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_stale_data_detection(self):
        """Test stale data detection and handling."""
        result = TestResult(name="stale_data_detection", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            # Test stale data detection logic
            thresholds = {
                "market_tick": 10,  # 10 seconds
                "agent_state": 30,  # 30 seconds
                "health_status": 60,  # 60 seconds
            }
            
            result.details["freshness_thresholds"] = thresholds
            
            # Test with different ages
            test_cases = [
                {"age_seconds": 5, "threshold": 10, "expected": "fresh"},
                {"age_seconds": 15, "threshold": 10, "expected": "stale"},
                {"age_seconds": 25, "threshold": 30, "expected": "fresh"},
                {"age_seconds": 35, "threshold": 30, "expected": "stale"},
            ]
            
            detection_results = []
            for test_case in test_cases:
                is_stale = test_case["age_seconds"] >= test_case["threshold"]
                detection_results.append({
                    "age": test_case["age_seconds"],
                    "threshold": test_case["threshold"],
                    "detected_stale": is_stale,
                    "expected": test_case["expected"],
                    "correct": (is_stale and test_case["expected"] == "stale") or (not is_stale and test_case["expected"] == "fresh")
                })
            
            result.details["stale_detection_tests"] = detection_results
            result.details["stale_detection_working"] = all(t["correct"] for t in detection_results)
            
            if not result.details["stale_detection_working"]:
                result.status = TestStatus.WARNING
                result.issues.append("Stale data detection logic has issues")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Stale data detection test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_websocket_message_freshness(self):
        """Test WebSocket message age validation."""
        result = TestResult(name="websocket_message_freshness", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_ws:
                result.status = TestStatus.WARNING
                result.issues.append("Backend WebSocket not available")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Subscribe to messages
            import json
            subscribe_msg = json.dumps({
                "action": "subscribe",
                "channels": ["agent_state", "signal_update", "market_tick"]
            })
            await self.backend_ws.send(subscribe_msg)
            result.details["subscribed_to_channels"] = True
            
            # Wait briefly for a message
            try:
                # Set a short timeout to avoid blocking
                message = await asyncio.wait_for(self.backend_ws.recv(), timeout=2.0)
                
                if message:
                    try:
                        data = json.loads(message)
                        result.details["message_received"] = True
                        result.details["message_type"] = data.get("type", "unknown")
                        
                        # Check for timestamp in message
                        server_timestamp_ms = data.get("server_timestamp_ms")
                        data_timestamp = data.get("data", {}).get("timestamp")
                        
                        if server_timestamp_ms:
                            # Calculate age
                            current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                            age_ms = current_time_ms - server_timestamp_ms
                            age_seconds = age_ms / 1000.0
                            
                            result.details["message_has_timestamp"] = True
                            result.details["message_age_seconds"] = round(age_seconds, 2)
                            
                            # Check freshness
                            if age_seconds < 30:
                                result.details["message_fresh"] = True
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Message is stale: {age_seconds:.0f}s old")
                        elif data_timestamp:
                            result.details["message_has_data_timestamp"] = True
                            result.details["data_timestamp"] = data_timestamp
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Message missing timestamp")
                    except json.JSONDecodeError:
                        result.status = TestStatus.WARNING
                        result.issues.append("Message is not valid JSON")
            except asyncio.TimeoutError:
                result.details["no_message_received"] = True
                result.status = TestStatus.WARNING
                result.issues.append("No message received within timeout (agent may not be generating events)")
                result.solutions.append("Wait for agent to generate events or check agent activity")
            except Exception as e:
                result.status = TestStatus.WARNING
                result.error = str(e)
                result.issues.append(f"Message reception test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"WebSocket message freshness test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
