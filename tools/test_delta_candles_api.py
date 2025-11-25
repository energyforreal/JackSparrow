#!/usr/bin/env python3
"""
Delta Exchange Candles API Validation Test

Automated test script to validate candles API fixes.
Runs after code changes to verify API integration is correct.
Exits with code 0 on success, non-zero on failure.
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from agent.data.delta_client import DeltaExchangeClient, DeltaExchangeError


def _is_production_url(url: str | None) -> bool:
    """Heuristic to detect live Delta endpoints."""
    if not url:
        return False
    lowered = url.lower()
    return "delta.exchange" in lowered and "testnet" not in lowered


def calculate_time_range(resolution: str, candle_count: int) -> tuple[int, int]:
    """Calculate start and end timestamps.
    
    Args:
        resolution: Candle resolution (e.g., "15m", "1h", "4h", "1d")
        candle_count: Number of candles to retrieve
        
    Returns:
        Tuple of (start_timestamp, end_timestamp) in Unix seconds
    """
    resolution_seconds = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
        "6h": 21600, "1d": 86400, "1w": 604800
    }
    
    seconds_per_candle = resolution_seconds.get(resolution.lower(), 3600)
    total_seconds = candle_count * seconds_per_candle
    
    end_time = int(time.time())
    start_time = end_time - total_seconds
    
    return start_time, end_time


async def test_candles_api(symbol: str, rate_limit: float):
    """Test candles API with various resolutions and counts."""
    try:
        client = DeltaExchangeClient()
    except Exception as e:
        print(f"FAIL: Failed to initialize client: {e}")
        return False
    
    test_cases = [
        {"resolution": "15m", "candle_count": 2},
        {"resolution": "15m", "candle_count": 10},
        {"resolution": "1h", "candle_count": 5},
        {"resolution": "4h", "candle_count": 3},
        {"resolution": "1d", "candle_count": 2},
    ]
    
    passed_tests = 0
    total_tests = len(test_cases)
    
    for test_case in test_cases:
        resolution = test_case["resolution"]
        candle_count = test_case["candle_count"]
        
        try:
            if rate_limit > 0:
                await asyncio.sleep(rate_limit)
            # Calculate time range
            start_time, end_time = calculate_time_range(resolution, candle_count)
            
            print(f"Testing: {resolution} x {candle_count} candles (start={start_time}, end={end_time})")
            
            # Make API call
            response = await client.get_candles(
                symbol=symbol,
                resolution=resolution,
                start=start_time,
                end=end_time
            )
            
            # Validate response structure
            if not response:
                print(f"FAIL: Empty response for {resolution} x {candle_count}")
                print(f"Response: {response}")
                continue
            
            # Handle different response structures
            # API might return {"result": {"candles": [...]}} or {"result": [...]} or just [...]
            candles = None
            if isinstance(response, dict):
                result = response.get("result")
                if result is None:
                    print(f"FAIL: No 'result' in response for {resolution} x {candle_count}")
                    print(f"Response keys: {list(response.keys())}")
                    print(f"Response: {response}")
                    continue
                
                if isinstance(result, dict):
                    candles = result.get("candles", [])
                elif isinstance(result, list):
                    candles = result
                else:
                    print(f"FAIL: Unexpected result type: {type(result)}")
                    print(f"Result: {result}")
                    continue
            elif isinstance(response, list):
                candles = response
            else:
                print(f"FAIL: Unexpected response type: {type(response)}")
                print(f"Response: {response}")
                continue
            
            if not candles:
                print(f"FAIL: No candles in response for {resolution} x {candle_count}")
                if isinstance(response, dict):
                    print(f"Response keys: {list(response.keys())}")
                continue
            
            # Validate candle data structure
            all_candles_valid = True
            for i, candle in enumerate(candles):
                required_fields = ["time", "open", "high", "low", "close", "volume"]
                missing_fields = [f for f in required_fields if f not in candle]
                if missing_fields:
                    print(f"FAIL: Missing fields {missing_fields} in candle {i}")
                    print(f"Candle data: {candle}")
                    all_candles_valid = False
                    break
            
            if not all_candles_valid:
                continue
            
            print(f"PASS: {resolution} x {candle_count} - Retrieved {len(candles)} candles")
            if len(candles) > 0:
                first_candle = candles[0]
                print(f"  First candle: time={first_candle.get('time')}, "
                      f"open={first_candle.get('open')}, close={first_candle.get('close')}")
            passed_tests += 1
            
        except DeltaExchangeError as e:
            print(f"FAIL: API error for {resolution} x {candle_count}: {e}")
            import traceback
            traceback.print_exc()
            continue
        except Exception as e:
            print(f"FAIL: Unexpected error for {resolution} x {candle_count}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\nTest Summary: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("SUCCESS: All test cases passed!")
        return True
    else:
        print(f"FAILURE: {total_tests - passed_tests} test case(s) failed")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Delta Exchange candles API")
    parser.add_argument("--symbol", default="BTCUSD", help="Trading symbol to test")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Acknowledge that this script will hit live Delta Exchange endpoints",
    )
    parser.add_argument(
        "--base-url",
        help="Override Delta Exchange base URL (defaults to env or https://api.india.delta.exchange)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.5,
        help="Seconds to wait between API requests (default: 0.5)",
    )
    args = parser.parse_args()
    
    target_url = (
        args.base_url
        or os.getenv("DELTA_EXCHANGE_BASE_URL")
        or os.getenv("DELTA_API_URL")
        or "https://api.india.delta.exchange"
    )
    os.environ["DELTA_EXCHANGE_BASE_URL"] = target_url
    
    if _is_production_url(target_url) and not args.allow_live:
        print(
            "Refusing to run against production Delta Exchange endpoints without --allow-live.\n"
            "Use --base-url https://api-testnet.delta.exchange (or another sandbox) to run safely."
        )
        sys.exit(2)
    
    print("=" * 60)
    print("Delta Exchange Candles API Validation Test")
    print("=" * 60)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")
    
    success = asyncio.run(test_candles_api(symbol=args.symbol, rate_limit=max(0.0, args.rate_limit)))
    
    print("\n" + "=" * 60)
    if success:
        print("All tests PASSED - API integration is correct")
    else:
        print("Some tests FAILED - API integration needs fixes")
    print("=" * 60)
    
    sys.exit(0 if success else 1)

