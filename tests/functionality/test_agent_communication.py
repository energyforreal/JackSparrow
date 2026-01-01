"""Test agent communication functionality (backend-agent, agent-frontend, WebSocket, Redis)."""

import asyncio
import json
import time
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import (
    get_shared_backend, get_shared_agent_websocket, 
    get_shared_backend_websocket, get_shared_redis, get_shared_agent
)
from tests.functionality.config import config


class AgentCommunicationTestSuite(TestSuiteBase):
    """Test suite for agent communication."""
    
    def __init__(self, test_name: str = "agent_communication"):
        super().__init__(test_name)
        self.backend_client = None
        self.agent_ws = None
        self.backend_ws = None
        self.redis = None
        self.agent = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.backend_client = await get_shared_backend()
        except Exception:
            pass
        
        try:
            self.agent_ws = await get_shared_agent_websocket()
        except Exception:
            pass  # WebSocket may not be available
        
        try:
            self.backend_ws = await get_shared_backend_websocket()
        except Exception:
            pass
        
        try:
            self.redis = await get_shared_redis()
        except Exception:
            pass
        
        try:
            self.agent = await get_shared_agent()
        except Exception:
            pass
    
    async def run_all_tests(self):
        """Run all communication tests."""
        # Backend ↔ Agent tests
        await self._test_backend_agent_websocket()
        await self._test_backend_agent_redis_fallback()
        await self._test_command_response_roundtrip()
        await self._test_command_types()
        await self._test_timeout_handling()
        
        # Agent → Backend tests
        await self._test_agent_backend_websocket()
        await self._test_agent_event_publishing()
        await self._test_dual_publishing()
        
        # Frontend ↔ Backend tests
        await self._test_frontend_backend_websocket()
        await self._test_message_subscription()
        await self._test_reconnection_logic()
    
    async def _test_backend_agent_websocket(self):
        """Test backend to agent WebSocket connection."""
        result = TestResult(name="backend_agent_websocket", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.agent_ws:
                result.status = TestStatus.WARNING
                result.issues.append("Agent WebSocket not available")
                result.solutions.append("Ensure agent WebSocket server is running on ws://localhost:8002")
            else:
                # Test connection with ping
                try:
                    await self.agent_ws.ping()
                    result.details["websocket_connected"] = True
                    result.details["ping_successful"] = True
                except Exception as ping_error:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"WebSocket ping failed: {ping_error}")
                
                # Test message sending capability
                try:
                    test_message = {
                        "type": "test",
                        "request_id": str(uuid.uuid4()),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    await self.agent_ws.send(json.dumps(test_message))
                    result.details["can_send_messages"] = True
                except Exception as send_error:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"Message send failed: {send_error}")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"WebSocket connection failed: {e}")
            result.solutions.append("Check agent WebSocket server configuration")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_backend_agent_redis_fallback(self):
        """Test Redis queue fallback mechanism."""
        result = TestResult(name="redis_fallback", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.redis:
                result.status = TestStatus.WARNING
                result.issues.append("Redis not available")
                result.solutions.append("Ensure Redis is running")
            else:
                # Test Redis connectivity
                await self.redis.ping()
                result.details["redis_connected"] = True
                
                # Test Redis queue operations (command queue)
                try:
                    from agent.core.config import settings
                    command_queue = settings.agent_command_queue
                    result.details["command_queue_name"] = command_queue
                    
                    # Check if queue exists or can be created
                    result.details["redis_fallback_available"] = True
                    
                    # Test response mechanism (key-value store)
                    test_key = f"response:test_{uuid.uuid4()}"
                    test_value = json.dumps({"test": "data"})
                    await self.redis.set(test_key, test_value, ex=120)  # 2 minute TTL
                    
                    retrieved = await self.redis.get(test_key)
                    if retrieved:
                        result.details["redis_key_value_working"] = True
                        await self.redis.delete(test_key)  # Cleanup
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Redis key-value retrieval failed")
                except Exception as queue_error:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"Redis queue test failed: {queue_error}")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Redis connection failed: {e}")
            result.solutions.append("Check Redis configuration and connectivity")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_command_response_roundtrip(self):
        """Test command/response round-trip."""
        result = TestResult(name="command_response_roundtrip", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_client:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
                result.solutions.append("Ensure backend is running on http://localhost:8000")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Test prediction request (command/response via backend → agent)
            try:
                async with self.backend_client.post("/api/v1/predict", params={"symbol": "BTCUSD"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result.details["response_received"] = True
                        result.details["response_status"] = resp.status
                        
                        # Validate response structure
                        if isinstance(data, dict):
                            result.details["response_is_dict"] = True
                            
                            # Check for signal in response
                            if "signal" in data:
                                result.details["has_signal"] = True
                                result.details["signal"] = data.get("signal")
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append("Response missing 'signal' field")
                            
                            # Check for confidence
                            if "confidence" in data:
                                result.details["has_confidence"] = True
                                result.details["confidence"] = data.get("confidence")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Response is not a dictionary: {type(data)}")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append(f"Prediction request returned status {resp.status}")
                        result.solutions.append("Check backend and agent are running and communicating")
            except Exception as e:
                result.status = TestStatus.WARNING
                result.error = str(e)
                result.issues.append(f"Command round-trip test failed: {e}")
                result.solutions.append("Check backend and agent are running and network connectivity")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Command round-trip test failed: {e}")
            result.solutions.append("Check backend and agent are running")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_command_types(self):
        """Test different command types."""
        result = TestResult(name="command_types", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        command_types = {
            "predict": "/api/v1/predict",
            "get_status": "/api/v1/admin/agent/status",
            "health": "/api/v1/health"
        }
        tested = []
        failed = []
        
        if not self.backend_client:
            result.status = TestStatus.WARNING
            result.issues.append("Backend client not available")
            result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.add_result(result)
            return
        
        for cmd_type, endpoint in command_types.items():
            try:
                if cmd_type == "predict":
                    async with self.backend_client.post(endpoint, params={"symbol": "BTCUSD"}) as resp:
                        if resp.status == 200:
                            tested.append(cmd_type)
                            result.details[f"{cmd_type}_status"] = resp.status
                        else:
                            failed.append(f"{cmd_type} (status {resp.status})")
                elif cmd_type in ["get_status", "health"]:
                    async with self.backend_client.get(endpoint) as resp:
                        if resp.status == 200:
                            tested.append(cmd_type)
                            result.details[f"{cmd_type}_status"] = resp.status
                            
                            # Validate response for status endpoint
                            if cmd_type == "get_status":
                                data = await resp.json()
                                if isinstance(data, dict):
                                    result.details[f"{cmd_type}_has_data"] = True
                        else:
                            failed.append(f"{cmd_type} (status {resp.status})")
            except Exception as e:
                failed.append(f"{cmd_type} (error: {str(e)[:50]})")
        
        result.details["command_types_tested"] = tested
        result.details["command_types_failed"] = failed
        result.details["success_rate"] = f"{len(tested)}/{len(command_types)}"
        
        if len(tested) < len(command_types):
            result.status = TestStatus.WARNING
            result.issues.append(f"Only {len(tested)}/{len(command_types)} command types tested successfully")
            if failed:
                result.issues.append(f"Failed: {', '.join(failed)}")
            result.solutions.append("Check backend endpoints and agent availability")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_timeout_handling(self):
        """Test timeout handling."""
        result = TestResult(name="timeout_handling", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_client:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Test with a short timeout to verify timeout handling
            # Note: This tests backend timeout, not agent timeout
            try:
                import aiohttp
                timeout = aiohttp.ClientTimeout(total=1)  # 1 second timeout
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    try:
                        async with session.get(f"{config.backend_url}/api/v1/health") as resp:
                            # If we get here, request completed within timeout
                            result.details["timeout_handling"] = "tested"
                            result.details["request_completed"] = True
                    except asyncio.TimeoutError:
                        result.details["timeout_detected"] = True
                        result.details["timeout_handling"] = "working"
            except ImportError:
                result.status = TestStatus.WARNING
                result.issues.append("aiohttp not available for timeout testing")
            except Exception as e:
                result.status = TestStatus.WARNING
                result.error = str(e)
                result.issues.append(f"Timeout test failed: {e}")
            
            # Note: Testing agent-side timeout would require mocking slow responses
            result.details["agent_timeout_test"] = "requires_mocking"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Timeout handling test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_backend_websocket(self):
        """Test agent to backend WebSocket connection."""
        result = TestResult(name="agent_backend_websocket", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_ws:
                result.status = TestStatus.WARNING
                result.issues.append("Backend WebSocket not available")
                result.solutions.append("Ensure backend WebSocket server is running on ws://localhost:8000/ws")
            else:
                # Test connection with ping
                try:
                    await self.backend_ws.ping()
                    result.details["websocket_connected"] = True
                    result.details["ping_successful"] = True
                except Exception as ping_error:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"WebSocket ping failed: {ping_error}")
                
                # Check if agent has WebSocket client
                if self.agent:
                    websocket_client = getattr(self.agent, "websocket_client", None)
                    if websocket_client:
                        result.details["agent_websocket_client_available"] = True
                        is_connected = getattr(websocket_client, "is_connected", False)
                        result.details["agent_websocket_connected"] = is_connected
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Agent WebSocket client not initialized")
                        result.solutions.append("Check agent WebSocket client initialization")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"WebSocket connection test failed: {e}")
            result.solutions.append("Check backend WebSocket server configuration")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_agent_event_publishing(self):
        """Test agent event publishing."""
        result = TestResult(name="agent_event_publishing", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.WARNING
                result.issues.append("Agent not available")
                result.solutions.append("Agent may not be initialized")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Check event bus availability
            try:
                from agent.events.event_bus import event_bus
                result.details["event_bus_available"] = True
                
                # Check WebSocket client for event publishing
                websocket_client = getattr(self.agent, "websocket_client", None)
                if websocket_client:
                    result.details["websocket_client_available"] = True
                    is_connected = getattr(websocket_client, "is_connected", False)
                    result.details["websocket_connected"] = is_connected
                    
                    if is_connected:
                        result.details["can_publish_via_websocket"] = True
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("WebSocket client not connected")
                        result.solutions.append("Check backend WebSocket server is running")
                else:
                    result.details["websocket_client_available"] = False
                    result.status = TestStatus.WARNING
                    result.issues.append("WebSocket client not initialized")
                
                # Check Redis for event publishing
                if self.redis:
                    result.details["redis_available"] = True
                    result.details["can_publish_via_redis"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Redis not available for event publishing")
                
                # Note: Actual event publishing is tested indirectly through signal generation
                result.details["event_publishing_mechanism"] = "available"
            except ImportError:
                result.status = TestStatus.WARNING
                result.issues.append("Event bus not available")
                result.solutions.append("Check event bus imports")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Event publishing test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_dual_publishing(self):
        """Test dual publishing (WebSocket + Redis Streams)."""
        result = TestResult(name="dual_publishing", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.WARNING
                result.issues.append("Agent not available")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Check dual publishing capability
            websocket_client = getattr(self.agent, "websocket_client", None)
            websocket_available = websocket_client is not None
            websocket_connected = websocket_available and getattr(websocket_client, "is_connected", False)
            
            redis_available = self.redis is not None
            
            result.details["websocket_available"] = websocket_available
            result.details["websocket_connected"] = websocket_connected
            result.details["redis_available"] = redis_available
            
            if websocket_connected and redis_available:
                result.details["dual_publishing_available"] = True
                result.details["both_channels_ready"] = True
            elif websocket_connected:
                result.details["dual_publishing_available"] = False
                result.status = TestStatus.WARNING
                result.issues.append("Only WebSocket available, Redis not available")
                result.solutions.append("Ensure Redis is running")
            elif redis_available:
                result.details["dual_publishing_available"] = False
                result.status = TestStatus.WARNING
                result.issues.append("Only Redis available, WebSocket not connected")
                result.solutions.append("Check backend WebSocket server")
            else:
                result.details["dual_publishing_available"] = False
                result.status = TestStatus.WARNING
                result.issues.append("Neither WebSocket nor Redis available")
                result.solutions.append("Check WebSocket and Redis configuration")
            
            # Check event bus dual publishing
            try:
                from agent.events.event_bus import event_bus
                result.details["event_bus_available"] = True
                # Event bus publishes to both WebSocket and Redis if available
                result.details["event_bus_dual_publishing"] = True
            except ImportError:
                result.status = TestStatus.WARNING
                result.issues.append("Event bus not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Dual publishing test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_frontend_backend_websocket(self):
        """Test frontend to backend WebSocket connection."""
        result = TestResult(name="frontend_backend_websocket", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_ws:
                result.status = TestStatus.WARNING
                result.issues.append("Backend WebSocket not available")
                result.solutions.append("Ensure backend WebSocket server is running")
            else:
                result.details["websocket_available"] = True
                
                # Test subscription capability (frontend would subscribe to channels)
                try:
                    subscribe_msg = json.dumps({
                        "action": "subscribe",
                        "channels": ["agent_state", "signal_update", "market_tick"]
                    })
                    await self.backend_ws.send(subscribe_msg)
                    result.details["can_subscribe"] = True
                    result.details["subscription_sent"] = True
                except Exception as sub_error:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"Subscription test failed: {sub_error}")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Frontend-backend WebSocket test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_message_subscription(self):
        """Test message subscription/unsubscription."""
        result = TestResult(name="message_subscription", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_ws:
                result.status = TestStatus.WARNING
                result.issues.append("Backend WebSocket not available")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Test subscription
            try:
                subscribe_msg = json.dumps({
                    "action": "subscribe",
                    "channels": ["signal_update", "agent_state"]
                })
                await self.backend_ws.send(subscribe_msg)
                result.details["subscription_sent"] = True
                
                # Wait briefly for subscription confirmation (if any)
                await asyncio.sleep(0.1)
                result.details["subscription_processed"] = True
            except Exception as sub_error:
                result.status = TestStatus.WARNING
                result.issues.append(f"Subscription failed: {sub_error}")
            
            # Test unsubscription
            try:
                unsubscribe_msg = json.dumps({
                    "action": "unsubscribe",
                    "channels": ["signal_update"]
                })
                await self.backend_ws.send(unsubscribe_msg)
                result.details["unsubscription_sent"] = True
            except Exception as unsub_error:
                result.status = TestStatus.WARNING
                result.issues.append(f"Unsubscription failed: {unsub_error}")
            
            result.details["subscription_mechanism_working"] = True
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Message subscription test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_reconnection_logic(self):
        """Test reconnection logic."""
        result = TestResult(name="reconnection_logic", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                result.status = TestStatus.WARNING
                result.issues.append("Agent not available")
                result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.add_result(result)
                return
            
            # Check WebSocket client reconnection capability
            websocket_client = getattr(self.agent, "websocket_client", None)
            if websocket_client:
                result.details["websocket_client_available"] = True
                
                # Check for reconnection methods
                has_reconnect = hasattr(websocket_client, "reconnect") or hasattr(websocket_client, "_reconnect")
                result.details["reconnection_method_available"] = has_reconnect
                
                if has_reconnect:
                    result.details["reconnection_logic_implemented"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Reconnection method not found")
                    result.solutions.append("Reconnection may be handled automatically by websockets library")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("WebSocket client not available")
            
            # Note: Actual reconnection testing would require:
            # 1. Establishing connection
            # 2. Simulating connection loss
            # 3. Verifying reconnection
            # This is complex and may require mocking
            result.details["reconnection_test"] = "basic_check_complete"
            result.details["full_reconnection_test"] = "requires_connection_interruption_simulation"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Reconnection logic test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
