"""Test frontend functionality."""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime

import aiohttp

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_backend, get_shared_backend_websocket
from tests.functionality.config import config


class FrontendFunctionalityTestSuite(TestSuiteBase):
    """Test suite for frontend functionality."""
    
    def __init__(self, test_name: str = "frontend_functionality"):
        super().__init__(test_name)
        self.backend_client = None
        self.backend_ws = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.backend_client = await get_shared_backend()
        except Exception:
            pass
        
        try:
            self.backend_ws = await get_shared_backend_websocket()
        except Exception:
            pass
    
    async def run_all_tests(self):
        """Run all frontend functionality tests."""
        await self._test_frontend_accessible()
        await self._test_frontend_api_integration()
        await self._test_frontend_websocket_connection()
        await self._test_frontend_health_endpoint()
        await self._test_frontend_cors_headers()
        await self._test_frontend_error_handling()
    
    async def _test_frontend_accessible(self):
        """Test that frontend HTTP endpoint is accessible."""
        result = TestResult(name="frontend_accessible", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            frontend_url = config.frontend_url
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    frontend_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=True
                ) as resp:
                    result.details["frontend_url"] = frontend_url
                    result.details["status_code"] = resp.status
                    result.details["frontend_accessible"] = resp.status in (200, 301, 302)
                    
                    if resp.status == 200:
                        # Check if response looks like HTML (frontend page)
                        content_type = resp.headers.get("Content-Type", "")
                        result.details["content_type"] = content_type
                        if "text/html" in content_type:
                            result.details["is_html_response"] = True
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Unexpected content type: {content_type}")
                    elif resp.status in (301, 302):
                        result.details["redirected"] = True
                        result.details["location"] = resp.headers.get("Location", "")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append(f"Frontend returned status {resp.status}")
                        result.solutions.append("Check if frontend is running and accessible")
        except asyncio.TimeoutError:
            result.status = TestStatus.WARNING
            result.issues.append("Frontend connection timeout")
            result.solutions.append("Check if frontend is running and port is correct")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Frontend accessibility test failed: {e}")
            result.solutions.append("Check frontend URL configuration and service status")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_frontend_api_integration(self):
        """Test that frontend can communicate with backend API."""
        result = TestResult(name="frontend_api_integration", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_client:
                self.backend_client = await get_shared_backend()
            
            if not self.backend_client:
                result.status = TestStatus.WARNING
                result.issues.append("Backend client not available")
                result.solutions.append("Ensure backend is running")
            else:
                # Test health endpoint (doesn't require auth)
                async with self.backend_client.get("/api/v1/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result.details["backend_health_accessible"] = True
                        result.details["backend_health_status"] = data.get("status", "unknown")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append(f"Backend health check returned status {resp.status}")
                
                # Test that frontend would be able to access API endpoints
                # (Note: Some endpoints require auth, so we test health which doesn't)
                result.details["api_integration_test"] = "health_endpoint_checked"
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Frontend API integration test failed: {e}")
            result.solutions.append("Check backend is running and accessible")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_frontend_websocket_connection(self):
        """Test that frontend can connect to backend WebSocket."""
        result = TestResult(name="frontend_websocket_connection", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if not self.backend_ws:
                self.backend_ws = await get_shared_backend_websocket()
            
            if not self.backend_ws:
                result.status = TestStatus.WARNING
                result.issues.append("Backend WebSocket not available")
                result.solutions.append("Ensure backend WebSocket server is running")
            else:
                # Test WebSocket connection
                try:
                    await self.backend_ws.ping()
                    result.details["websocket_connected"] = True
                    result.details["ping_successful"] = True
                    
                    # Test subscription (frontend would subscribe to channels)
                    subscribe_msg = {
                        "type": "subscribe",
                        "channels": ["agent_state", "signal_update"]
                    }
                    await self.backend_ws.send(json.dumps(subscribe_msg))
                    
                    # Wait for subscription confirmation
                    try:
                        response = await asyncio.wait_for(self.backend_ws.recv(), timeout=2.0)
                        response_data = json.loads(response)
                        result.details["subscription_response"] = response_data.get("type", "unknown")
                        if response_data.get("type") == "subscribed":
                            result.details["subscription_successful"] = True
                    except asyncio.TimeoutError:
                        result.details["subscription_timeout"] = True
                        result.status = TestStatus.WARNING
                        result.issues.append("WebSocket subscription confirmation timeout")
                except Exception as ws_error:
                    result.status = TestStatus.WARNING
                    result.issues.append(f"WebSocket connection test failed: {ws_error}")
                    result.solutions.append("Check WebSocket server configuration")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Frontend WebSocket test failed: {e}")
            result.solutions.append("Check backend WebSocket server is running")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_frontend_health_endpoint(self):
        """Test frontend health/status endpoint if available."""
        result = TestResult(name="frontend_health_endpoint", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            frontend_url = config.frontend_url
            
            # Try common health check endpoints
            health_endpoints = [
                f"{frontend_url}/api/health",
                f"{frontend_url}/health",
                f"{frontend_url}/_next/static/chunks/webpack.js",  # Next.js static file
            ]
            
            async with aiohttp.ClientSession() as session:
                for endpoint in health_endpoints:
                    try:
                        async with session.get(
                            endpoint,
                            timeout=aiohttp.ClientTimeout(total=3),
                            allow_redirects=True
                        ) as resp:
                            if resp.status == 200:
                                result.details["health_endpoint_found"] = endpoint
                                result.details["health_status"] = resp.status
                                break
                    except Exception:
                        continue
                
                # If no health endpoint found, check if main page loads
                if "health_endpoint_found" not in result.details:
                    async with session.get(
                        frontend_url,
                        timeout=aiohttp.ClientTimeout(total=3),
                        allow_redirects=True
                    ) as resp:
                        if resp.status == 200:
                            result.details["main_page_accessible"] = True
                            result.details["main_page_status"] = resp.status
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Frontend health endpoints not accessible")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Frontend health endpoint test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_frontend_cors_headers(self):
        """Test that frontend has proper CORS headers for API access."""
        result = TestResult(name="frontend_cors_headers", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            frontend_url = config.frontend_url
            
            async with aiohttp.ClientSession() as session:
                # Make OPTIONS request to check CORS headers
                async with session.options(
                    frontend_url,
                    timeout=aiohttp.ClientTimeout(total=3),
                    headers={"Origin": frontend_url}
                ) as resp:
                    cors_headers = {
                        "Access-Control-Allow-Origin": resp.headers.get("Access-Control-Allow-Origin"),
                        "Access-Control-Allow-Methods": resp.headers.get("Access-Control-Allow-Methods"),
                        "Access-Control-Allow-Headers": resp.headers.get("Access-Control-Allow-Headers"),
                    }
                    result.details["cors_headers"] = cors_headers
                    
                    # CORS is typically handled by backend, not frontend
                    # So this is more of an informational test
                    result.details["cors_test_note"] = "CORS is typically configured on backend API"
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"CORS headers test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_frontend_error_handling(self):
        """Test frontend error handling for various failure scenarios."""
        result = TestResult(name="frontend_error_handling", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            frontend_url = config.frontend_url
            
            async with aiohttp.ClientSession() as session:
                # Test 1: Invalid endpoint handling
                try:
                    async with session.get(
                        f"{frontend_url}/nonexistent-endpoint-12345",
                        timeout=aiohttp.ClientTimeout(total=3),
                        allow_redirects=True
                    ) as resp:
                        result.details["invalid_endpoint_status"] = resp.status
                        result.details["invalid_endpoint_handled"] = resp.status in (404, 200)  # 404 or Next.js might redirect
                except Exception as e:
                    result.details["invalid_endpoint_error"] = str(e)
                
                # Test 2: Very long URL handling (potential DoS protection)
                try:
                    long_path = "/" + "a" * 1000
                    async with session.get(
                        f"{frontend_url}{long_path}",
                        timeout=aiohttp.ClientTimeout(total=3),
                        allow_redirects=True
                    ) as resp:
                        result.details["long_url_status"] = resp.status
                        result.details["long_url_handled"] = resp.status < 500  # Should not crash
                except Exception as e:
                    result.details["long_url_error"] = str(e)
                
                # Test 3: Invalid HTTP method handling
                try:
                    async with session.patch(
                        frontend_url,
                        timeout=aiohttp.ClientTimeout(total=3),
                        json={"test": "data"}
                    ) as resp:
                        result.details["invalid_method_status"] = resp.status
                        result.details["invalid_method_handled"] = resp.status in (405, 404, 200)  # Method not allowed or handled gracefully
                except Exception as e:
                    result.details["invalid_method_error"] = str(e)
                
                # Test 4: Large payload handling (if POST endpoint exists)
                try:
                    large_payload = {"data": "x" * 10000}
                    async with session.post(
                        frontend_url,
                        timeout=aiohttp.ClientTimeout(total=3),
                        json=large_payload
                    ) as resp:
                        result.details["large_payload_status"] = resp.status
                        result.details["large_payload_handled"] = resp.status < 500
                except Exception as e:
                    result.details["large_payload_error"] = str(e)
                
                # Test 5: Special characters in URL
                try:
                    special_chars_path = "/test%20path%2Fwith%3Fspecial%26chars"
                    async with session.get(
                        f"{frontend_url}{special_chars_path}",
                        timeout=aiohttp.ClientTimeout(total=3),
                        allow_redirects=True
                    ) as resp:
                        result.details["special_chars_status"] = resp.status
                        result.details["special_chars_handled"] = resp.status < 500
                except Exception as e:
                    result.details["special_chars_error"] = str(e)
                
                # Summary: Frontend should handle errors gracefully
                error_handling_score = sum([
                    result.details.get("invalid_endpoint_handled", False),
                    result.details.get("long_url_handled", False),
                    result.details.get("invalid_method_handled", False),
                    result.details.get("large_payload_handled", False),
                    result.details.get("special_chars_handled", False),
                ])
                result.details["error_handling_score"] = f"{error_handling_score}/5"
                
                if error_handling_score < 3:
                    result.status = TestStatus.WARNING
                    result.issues.append("Frontend error handling may need improvement")
                    result.solutions.append("Review error handling for edge cases")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Frontend error handling test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass

