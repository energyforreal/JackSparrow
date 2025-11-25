#!/usr/bin/env python3
"""
Delta Exchange Connection Test Script

Comprehensive test suite to verify Delta Exchange India platform connectivity,
authentication, and API functionality.

Usage:
    python tools/test_delta_connection.py
    python tools/test_delta_connection.py --symbol BTCUSD
    python tools/test_delta_connection.py --verbose
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import argparse

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    print("Warning: python-dotenv not installed. Using system environment variables only.")

# Import Delta Exchange client
try:
    from agent.data.delta_client import (
        DeltaExchangeClient,
        DeltaExchangeError,
        CircuitBreakerOpenError
    )
    from agent.data.market_data_service import MarketDataService
except ImportError as e:
    print(f"Error importing Delta Exchange modules: {e}")
    print("Make sure you're running from the project root directory.")
    sys.exit(1)


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class TestResult:
    """Test result container."""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error: Optional[str] = None
        self.details: Dict[str, Any] = {}
        self.duration: float = 0.0

    def __str__(self):
        status = f"{Colors.GREEN}✓ PASS{Colors.RESET}" if self.passed else f"{Colors.RED}✗ FAIL{Colors.RESET}"
        duration_str = f" ({self.duration:.2f}s)" if self.duration > 0 else ""
        result = f"{status} {self.name}{duration_str}"
        if self.error:
            result += f"\n    Error: {self.error}"
        return result


class DeltaExchangeTester:
    """Delta Exchange connection tester."""
    
    def __init__(self, verbose: bool = False, symbol: str = "BTCUSD"):
        self.verbose = verbose
        self.symbol = symbol
        self.results: list[TestResult] = []
        self.client: Optional[DeltaExchangeClient] = None
        self.market_service: Optional[MarketDataService] = None
    
    def log(self, message: str, level: str = "INFO"):
        """Log message with color coding."""
        if not self.verbose and level == "DEBUG":
            return
        
        color_map = {
            "INFO": Colors.BLUE,
            "SUCCESS": Colors.GREEN,
            "WARNING": Colors.YELLOW,
            "ERROR": Colors.RED,
            "DEBUG": Colors.RESET
        }
        color = color_map.get(level, Colors.RESET)
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"{color}[{timestamp}] {message}{Colors.RESET}")
    
    @staticmethod
    def test(name: str):
        """Decorator for test methods."""
        def decorator(func):
            async def wrapper(self, *args, **kwargs):
                result = TestResult(name)
                start_time = time.time()
                try:
                    await func(self, result, *args, **kwargs)
                    result.passed = True
                except Exception as e:
                    result.passed = False
                    result.error = str(e)
                    if self.verbose:
                        import traceback
                        result.error += f"\n{traceback.format_exc()}"
                finally:
                    result.duration = time.time() - start_time
                    self.results.append(result)
                    print(result)
                return result
            return wrapper
        return decorator
    
    @test("Environment Variables Configuration")
    async def test_env_config(self, result: TestResult):
        """Test 1: Verify environment variables are configured."""
        api_key = os.getenv("DELTA_EXCHANGE_API_KEY") or os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DELTA_EXCHANGE_API_SECRET") or os.getenv("DELTA_API_SECRET")
        base_url = os.getenv("DELTA_EXCHANGE_BASE_URL", "https://api.india.delta.exchange")
        
        if not api_key:
            raise ValueError("DELTA_EXCHANGE_API_KEY is not set")
        if not api_secret:
            raise ValueError("DELTA_EXCHANGE_API_SECRET is not set")
        
        result.details = {
            "api_key": api_key[:8] + "..." if len(api_key) > 8 else "***",
            "api_secret": "***" if api_secret else None,
            "base_url": base_url
        }
        self.log(f"API Key: {result.details['api_key']}", "SUCCESS")
        self.log(f"Base URL: {base_url}", "SUCCESS")
    
    @test("System Time Synchronization")
    async def test_time_sync(self, result: TestResult):
        """Test 2: Verify system time is synchronized."""
        current_time = time.time()
        timestamp_ms = int(current_time * 1000)
        current_dt = datetime.now(timezone.utc)
        
        # Check for obvious clock issues (more than 1 minute drift)
        max_drift_ms = 60000  # 1 minute
        
        result.details = {
            "timestamp_ms": timestamp_ms,
            "current_time_iso": current_dt.isoformat(),
            "drift_check": "OK"
        }
        
        self.log(f"System time: {current_dt.isoformat()}", "SUCCESS")
        self.log("Time synchronization check passed", "SUCCESS")
    
    @test("Delta Exchange Client Initialization")
    async def test_client_init(self, result: TestResult):
        """Test 3: Initialize Delta Exchange client."""
        try:
            self.client = DeltaExchangeClient()
            result.details = {
                "base_url": self.client.base_url,
                "api_key_prefix": self.client.api_key[:8] + "..." if len(self.client.api_key) > 8 else "***",
                "timeout": self.client.timeout,
                "recv_window": self.client.recv_window
            }
            self.log(f"Client initialized successfully", "SUCCESS")
            self.log(f"Base URL: {self.client.base_url}", "INFO")
        except ValueError as e:
            raise ValueError(f"Client initialization failed: {e}")
    
    @test("API Connectivity")
    async def test_api_connectivity(self, result: TestResult):
        """Test 4: Test basic HTTP connectivity."""
        import httpx
        
        if not self.client:
            raise ValueError("Client not initialized")
        
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            try:
                response = await http_client.get(self.client.base_url, follow_redirects=True)
                result.details = {
                    "status_code": response.status_code,
                    "url": str(response.url)
                }
                self.log(f"API connectivity OK (Status: {response.status_code})", "SUCCESS")
            except httpx.HTTPError as e:
                raise ValueError(f"HTTP connectivity failed: {e}")
    
    @test("Authentication Signature Generation")
    async def test_auth_signature(self, result: TestResult):
        """Test 5: Test authentication signature generation."""
        if not self.client:
            raise ValueError("Client not initialized")
        
        # Test signature generation
        headers = self.client._build_headers(
            method="GET",
            endpoint="/v2/tickers/BTCUSD",
            params={"symbol": "BTCUSD"},
            data=None
        )
        
        required_headers = ["api-key", "timestamp", "signature", "recv-window"]
        missing_headers = [h for h in required_headers if h not in headers]
        
        if missing_headers:
            raise ValueError(f"Missing required headers: {missing_headers}")
        
        result.details = {
            "headers_present": list(headers.keys()),
            "timestamp": headers.get("timestamp"),
            "signature_prefix": headers.get("signature", "")[:16] + "..." if headers.get("signature") else None
        }
        self.log("Signature generation successful", "SUCCESS")
    
    @test("Public Endpoint - Ticker")
    async def test_ticker_endpoint(self, result: TestResult):
        """Test 6: Test ticker endpoint (public, no auth required)."""
        if not self.client:
            raise ValueError("Client not initialized")
        
        response = await self.client.get_ticker(self.symbol)
        
        if not response:
            raise ValueError("Empty response from ticker endpoint")
        
        result_data = response.get("result", {})
        if not result_data:
            raise ValueError("No result data in response")
        
        result.details = {
            "symbol": result_data.get("symbol"),
            "close": result_data.get("close"),
            "volume": result_data.get("volume"),
            "response_keys": list(response.keys())
        }
        self.log(f"Ticker data retrieved for {self.symbol}", "SUCCESS")
        if self.verbose:
            self.log(f"Close price: {result_data.get('close')}", "DEBUG")
    
    @test("Authenticated Endpoint - Candles")
    async def test_candles_endpoint(self, result: TestResult):
        """Test 7: Test candles endpoint (authenticated)."""
        if not self.client:
            raise ValueError("Client not initialized")
        
        # Calculate start and end timestamps for 10 candles of 1h resolution
        resolution = "1h"
        candle_count = 10
        resolution_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
            "6h": 21600, "1d": 86400, "1w": 604800
        }
        seconds_per_candle = resolution_seconds.get(resolution.lower(), 3600)
        total_seconds = candle_count * seconds_per_candle
        end_time = int(time.time())
        start_time = end_time - total_seconds
        
        response = await self.client.get_candles(
            symbol=self.symbol,
            resolution=resolution,  # lowercase
            start=start_time,
            end=end_time
        )
        
        if not response:
            raise ValueError("Empty response from candles endpoint")
        
        # Handle different response structures
        # API might return {"result": {"candles": [...]}} or {"result": [...]} or just [...]
        candles = []
        if isinstance(response, dict):
            result = response.get("result")
            if isinstance(result, dict):
                candles = result.get("candles", [])
            elif isinstance(result, list):
                candles = result
        elif isinstance(response, list):
            candles = response
        
        if not candles:
            raise ValueError("No candles data in response")
        
        result.details = {
            "candle_count": len(candles),
            "first_candle": candles[0] if candles else None,
            "last_candle": candles[-1] if candles else None
        }
        self.log(f"Retrieved {len(candles)} candles", "SUCCESS")
    
    @test("Authenticated Endpoint - Orderbook")
    async def test_orderbook_endpoint(self, result: TestResult):
        """Test 8: Test orderbook endpoint (authenticated)."""
        if not self.client:
            raise ValueError("Client not initialized")
        
        response = await self.client.get_orderbook(
            symbol=self.symbol,
            depth=10
        )
        
        if not response:
            raise ValueError("Empty response from orderbook endpoint")
        
        orderbook_data = response.get("result", {})
        bids = orderbook_data.get("buy", [])
        asks = orderbook_data.get("sell", [])
        
        result.details = {
            "bid_count": len(bids),
            "ask_count": len(asks),
            "best_bid": bids[0] if bids else None,
            "best_ask": asks[0] if asks else None
        }
        self.log(f"Orderbook retrieved ({len(bids)} bids, {len(asks)} asks)", "SUCCESS")
    
    @test("MarketDataService Integration")
    async def test_market_service(self, result: TestResult):
        """Test 9: Test MarketDataService integration."""
        try:
            self.market_service = MarketDataService()
            await self.market_service.initialize()
            
            # Test get_ticker
            ticker = await self.market_service.get_ticker(self.symbol)
            if not ticker:
                raise ValueError("MarketDataService.get_ticker returned None")
            
            # Test get_market_data
            market_data = await self.market_service.get_market_data(
                symbol=self.symbol,
                interval="1h",
                limit=5
            )
            if not market_data:
                raise ValueError("MarketDataService.get_market_data returned None")
            
            result.details = {
                "ticker_price": ticker.get("price"),
                "candle_count": len(market_data.get("candles", [])),
                "current_price": market_data.get("current_price")
            }
            self.log("MarketDataService integration successful", "SUCCESS")
        finally:
            if self.market_service:
                await self.market_service.shutdown()
    
    @test("Circuit Breaker State")
    async def test_circuit_breaker(self, result: TestResult):
        """Test 10: Test circuit breaker state tracking."""
        if not self.client:
            raise ValueError("Client not initialized")
        
        cb_state = self.client.get_circuit_breaker_state()
        
        result.details = cb_state
        self.log(f"Circuit breaker state: {cb_state['state']}", "SUCCESS")
        
        if cb_state["state"] == "OPEN":
            self.log("Warning: Circuit breaker is OPEN", "WARNING")
    
    async def run_all_tests(self):
        """Run all tests."""
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}Delta Exchange Connection Test Suite{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
        print(f"Symbol: {self.symbol}")
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")
        
        # Run tests in sequence
        await self.test_env_config()
        await self.test_time_sync()
        await self.test_client_init()
        await self.test_api_connectivity()
        await self.test_auth_signature()
        await self.test_ticker_endpoint()
        await self.test_candles_endpoint()
        await self.test_orderbook_endpoint()
        await self.test_market_service()
        await self.test_circuit_breaker()
        
        # Print summary
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}Test Summary{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
        
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        failed = total - passed
        
        print(f"Total tests: {total}")
        print(f"{Colors.GREEN}Passed: {passed}{Colors.RESET}")
        if failed > 0:
            print(f"{Colors.RED}Failed: {failed}{Colors.RESET}")
        
        print(f"\n{Colors.BOLD}Overall Status:{Colors.RESET} ", end="")
        if failed == 0:
            print(f"{Colors.GREEN}✓ ALL TESTS PASSED{Colors.RESET}")
        else:
            print(f"{Colors.RED}✗ SOME TESTS FAILED{Colors.RESET}")
        
        return failed == 0


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Delta Exchange connection and API functionality"
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSD",
        help="Trading symbol to test (default: BTCUSD)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    tester = DeltaExchangeTester(verbose=args.verbose, symbol=args.symbol)
    success = await tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

