"""Comprehensive backend health check.

This script checks if the backend service is running and accessible,
providing detailed diagnostics for troubleshooting.
"""

import asyncio
import httpx
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def check_backend_health() -> bool:
    """Check backend service health.
    
    Returns:
        True if backend is healthy, False otherwise
    """
    base_url = "http://localhost:8000"
    endpoints = {
        "health": f"{base_url}/api/v1/health",
        "docs": f"{base_url}/docs",
        "openapi": f"{base_url}/openapi.json",
    }
    
    results: Dict[str, Dict[str, Any]] = {}
    
    print("\n" + "=" * 50)
    print("  Backend Health Check")
    print("=" * 50 + "\n")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, url in endpoints.items():
            try:
                response = await client.get(url)
                results[name] = {
                    "status": "up",
                    "status_code": response.status_code,
                    "response_time_ms": response.elapsed.total_seconds() * 1000,
                    "content_length": len(response.content) if response.content else 0,
                }
                
                if name == "health" and response.status_code == 200:
                    try:
                        results[name]["data"] = response.json()
                    except Exception:
                        results[name]["data"] = None
                        
            except httpx.ConnectError:
                results[name] = {
                    "status": "down",
                    "error": "Connection refused - service not running",
                }
            except httpx.TimeoutException:
                results[name] = {
                    "status": "timeout",
                    "error": "Request timed out (>10s)",
                }
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "error": str(e),
                }
    
    # Print results
    all_up = True
    for name, result in results.items():
        status = result.get("status", "unknown")
        status_icon = "✓" if status == "up" else "✗"
        color_code = "\033[92m" if status == "up" else "\033[91m"  # Green/Red
        
        print(f"{status_icon} {name.upper():12} : {status.upper()}")
        
        if status == "up":
            if "status_code" in result:
                print(f"   Status Code    : {result['status_code']}")
            if "response_time_ms" in result:
                print(f"   Response Time  : {result['response_time_ms']:.2f} ms")
            if "data" in result and result["data"]:
                health_data = result["data"]
                print(f"   Overall Status : {health_data.get('status', 'unknown')}")
                if "health_score" in health_data:
                    score = health_data["health_score"]
                    score_color = "\033[92m" if score >= 0.9 else "\033[93m" if score >= 0.6 else "\033[91m"
                    print(f"   Health Score   : {score_color}{score:.3f}\033[0m")
                if "degradation_reasons" in health_data and health_data["degradation_reasons"]:
                    print(f"   Issues         : {', '.join(health_data['degradation_reasons'])}")
        else:
            all_up = False
            if "error" in result:
                print(f"   Error          : {result['error']}")
        print()
    
    # Provide troubleshooting steps if backend is down
    if not all_up or results.get("health", {}).get("status") != "up":
        print("⚠️  Backend service is not running or not accessible\n")
        print("Troubleshooting steps:")
        print("1. Check if backend is running:")
        print("   python -m backend.api.main")
        print("   OR")
        print("   uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload")
        print()
        print("2. Check if port 8000 is in use:")
        print("   Windows: netstat -ano | findstr :8000")
        print("   Linux/Mac: lsof -i :8000")
        print()
        print("3. Verify environment variables are set:")
        print("   Check that .env file exists with required variables")
        print()
        print("4. Review backend logs for startup errors:")
        print("   Check logs/ directory for error messages")
        print()
        return False
    
    print("✓ Backend is healthy and accessible\n")
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(check_backend_health())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nHealth check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError running health check: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
