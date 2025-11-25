#!/usr/bin/env python3
"""
Post-startup health check script for JackSparrow Trading Agent.

Validates that all services are healthy and responding after startup.
Can be run independently or integrated into startup process.
"""

import os
import sys
import time
import socket
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Set UTF-8 encoding for stdout/stderr on Windows to prevent encoding errors
if platform.system() == "Windows":
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        # Python < 3.7 or encoding not available, use ASCII-safe characters
        pass

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    try:
        import requests
        REQUESTS_AVAILABLE = True
    except ImportError:
        REQUESTS_AVAILABLE = False


class Colors:
    """Terminal color codes."""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# ASCII-safe symbols for Windows compatibility
class Symbols:
    """ASCII-safe symbols for cross-platform compatibility."""
    def __init__(self):
        is_windows = platform.system() == "Windows"
        self.CHECK = "[OK]" if is_windows else "✓"
        self.WARNING = "[WARN]" if is_windows else "⚠"
        self.CROSS = "[FAIL]" if is_windows else "✗"
        self.SUCCESS = "[SUCCESS]" if is_windows else "✅"


_symbols = Symbols()


class HealthChecker:
    """Checks health of all services."""
    
    def __init__(self, backend_url: str = "http://localhost:8000", 
                 frontend_url: str = "http://localhost:3000",
                 timeout: float = 10.0):
        """Initialize health checker.
        
        Args:
            backend_url: Backend API URL
            frontend_url: Frontend URL
            timeout: Request timeout in seconds
        """
        self.backend_url = backend_url.rstrip("/")
        self.frontend_url = frontend_url.rstrip("/")
        self.timeout = timeout
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.checks_passed = 0
        self.checks_failed = 0
        self.last_backend_health: Optional[Dict[str, Any]] = None
        
        if not HTTPX_AVAILABLE and not REQUESTS_AVAILABLE:
            self.errors.append(
                "No HTTP client library available. Install httpx or requests: "
                "pip install httpx"
            )
    
    def check_port_accessible(self, host: str, port: int, timeout: float = 2.0) -> bool:
        """Check if a TCP port is accessible.
        
        Args:
            host: Hostname or IP address
            port: Port number
            timeout: Connection timeout in seconds
            
        Returns:
            True if port is accessible, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception as e:
            # Log exception for debugging but don't fail loudly
            # Windows firewall or timing issues can cause false negatives
            return False
    
    def check_backend_health(self) -> bool:
        """Check backend health endpoint.
        
        Returns:
            True if backend is healthy, False otherwise
        """
        health_url = f"{self.backend_url}/api/v1/health"
        self.last_backend_health = None
        
        try:
            if HTTPX_AVAILABLE:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(health_url)
            elif REQUESTS_AVAILABLE:
                response = requests.get(health_url, timeout=self.timeout)
            else:
                self.errors.append("Cannot check backend health: No HTTP client available")
                return False
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    status = data.get("status", "unknown")
                    health_score = data.get("health_score", 0.0)
                    
                    health_details = {
                        "status": status,
                        "health_score": health_score,
                        "services": services,
                        "degradation_reasons": data.get("degradation_reasons", []),
                    }
                    self.last_backend_health = health_details
                    
                    if status == "healthy":
                        print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Backend health: {status} (score: {health_score:.2f})")
                        self.checks_passed += 1
                        
                        # Check individual services
                        services = data.get("services", {})
                        self._check_service_status("database", services.get("database"))
                        self._check_service_status("redis", services.get("redis"))
                        self._check_service_status("agent", services.get("agent"))
                        
                        return True
                    elif status == "degraded":
                        print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Backend health: {status} (score: {health_score:.2f})")
                        self.warnings.append(f"Backend is degraded (health score: {health_score:.2f})")
                        degradation_reasons = data.get("degradation_reasons", [])
                        if degradation_reasons:
                            for reason in degradation_reasons:
                                self.warnings.append(f"  - {reason}")
                        self.checks_passed += 1
                        return True
                    else:
                        print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Backend health: {status} (score: {health_score:.2f})")
                        self.errors.append(f"Backend is unhealthy (status: {status}, score: {health_score:.2f})")
                        self.checks_failed += 1
                        return False
                except Exception as e:
                    self.errors.append(f"Failed to parse backend health response: {e}")
                    self.checks_failed += 1
                    return False
            else:
                self.errors.append(f"Backend health endpoint returned status {response.status_code}")
                self.checks_failed += 1
                return False
                
        except Exception as e:
            self.errors.append(f"Backend health check failed: {e}")
            self.checks_failed += 1
            return False
    
    def _check_service_status(self, service_name: str, service_data: Optional[Dict]) -> None:
        """Check individual service status from health response.
        
        Args:
            service_name: Name of the service
            service_data: Service status data from health endpoint
        """
        if not service_data:
            self.warnings.append(f"{service_name.capitalize()} status not available in health response")
            return
        
        status = service_data.get("status", "unknown")
        if status == "up":
            print(f"  {Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {service_name.capitalize()}: {status}")
        elif status == "down":
            error = service_data.get("error", "Unknown error")
            print(f"  {Colors.RED}{_symbols.CROSS}{Colors.RESET} {service_name.capitalize()}: {status} - {error}")
            self.warnings.append(f"{service_name.capitalize()} is down: {error}")
        else:
            print(f"  {Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} {service_name.capitalize()}: {status}")
            self.warnings.append(f"{service_name.capitalize()} status is {status}")
    
    def check_backend_port(self, is_critical: bool = False) -> bool:
        """Check if backend port is accessible.
        
        Args:
            is_critical: If False, only warn instead of failing when port check fails
                        (useful when health endpoint works but port check has issues)
        
        Returns:
            True if port is accessible, False otherwise
        """
        parsed = urlparse(self.backend_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        
        # Use longer timeout for port check (Windows may need more time)
        if self.check_port_accessible(host, port, timeout=3.0):
            print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Backend port {port} is accessible")
            self.checks_passed += 1
            return True
        else:
            if is_critical:
                self.errors.append(f"Backend port {port} is not accessible")
                self.checks_failed += 1
                return False
            else:
                # Non-critical: just warn if health endpoint works
                self.warnings.append(
                    f"Backend port {port} port check failed, but health endpoint may still work "
                    "(this can happen on Windows due to firewall or timing issues)"
                )
                return False
    
    def check_frontend_accessible(self) -> bool:
        """Check if frontend is accessible.
        
        Returns:
            True if frontend is accessible, False otherwise
        """
        try:
            if HTTPX_AVAILABLE:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    response = client.get(self.frontend_url)
            elif REQUESTS_AVAILABLE:
                response = requests.get(self.frontend_url, timeout=self.timeout, allow_redirects=True)
            else:
                # Fallback to port check
                parsed = urlparse(self.frontend_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 3000
                if self.check_port_accessible(host, port):
                    print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Frontend port {port} is accessible")
                    self.checks_passed += 1
                    return True
                else:
                    self.errors.append(f"Frontend port {port} is not accessible")
                    self.checks_failed += 1
                    return False
            
            if response.status_code in (200, 301, 302):
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Frontend is accessible at {self.frontend_url}")
                self.checks_passed += 1
                return True
            else:
                self.errors.append(f"Frontend returned status {response.status_code}")
                self.checks_failed += 1
                return False
                
        except Exception as e:
            # Try port check as fallback
            parsed = urlparse(self.frontend_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 3000
            if self.check_port_accessible(host, port):
                print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Frontend port {port} is accessible but HTTP check failed: {e}")
                self.warnings.append(f"Frontend HTTP check failed: {e}")
                self.checks_passed += 1
                return True
            else:
                self.errors.append(f"Frontend is not accessible: {e}")
                self.checks_failed += 1
                return False
    
    def backend_port_status(self) -> Dict[str, Any]:
        """Return backend port reachability details."""
        parsed = urlparse(self.backend_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        reachable = self.check_port_accessible(host, port, timeout=3.0)
        return {"host": host, "port": port, "reachable": reachable}
    
    def frontend_port_status(self) -> Dict[str, Any]:
        """Return frontend port reachability details."""
        parsed = urlparse(self.frontend_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 3000
        reachable = self.check_port_accessible(host, port, timeout=3.0)
        return {"host": host, "port": port, "reachable": reachable}
    
    def get_backend_health_details(self) -> Optional[Dict[str, Any]]:
        """Return last cached backend health payload."""
        return self.last_backend_health
    
    def check_agent_status(self) -> Dict[str, Any]:
        """Query agent status endpoint for detailed info."""
        status: Dict[str, Any] = {"available": False}
        agent_url = f"{self.backend_url}/api/v1/agent/status"
        
        if not (HTTPX_AVAILABLE or REQUESTS_AVAILABLE):
            self.warnings.append(
                "Cannot check agent status: install httpx or requests (pip install httpx)"
            )
            status["error"] = "No HTTP client available"
            return status
        
        try:
            if HTTPX_AVAILABLE:
                with httpx.Client(timeout=self.timeout) as client:  # type: ignore[name-defined]
                    response = client.get(agent_url)
            else:
                response = requests.get(agent_url, timeout=self.timeout)  # type: ignore[name-defined]
            
            status["status_code"] = response.status_code
            if response.status_code == 200:
                data = response.json()
                status.update(data)
                status["available"] = True
            else:
                status["error"] = f"HTTP {response.status_code}"
        except Exception as exc:
            status["error"] = str(exc)
            self.warnings.append(f"Agent status check failed: {exc}")
        
        return status
    
    def check_all(self, wait_for_services: bool = True, max_wait: int = 30) -> bool:
        """Run all health checks.
        
        Args:
            wait_for_services: If True, wait for services to become available
            max_wait: Maximum seconds to wait for services
            
        Returns:
            True if all checks pass, False otherwise
        """
        print(f"{Colors.BOLD}Running Health Checks...{Colors.RESET}\n")
        
        if wait_for_services:
            print(f"Waiting up to {max_wait} seconds for services to become available...")
            start_time = time.time()
            backend_ready = False
            frontend_ready = False
            
            while time.time() - start_time < max_wait:
                # Check backend port
                parsed = urlparse(self.backend_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 8000
                if not backend_ready and self.check_port_accessible(host, port, timeout=1.0):
                    backend_ready = True
                    print(f"{Colors.GREEN}Backend port {port} is ready{Colors.RESET}")
                
                # Check frontend port
                parsed = urlparse(self.frontend_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 3000
                if not frontend_ready and self.check_port_accessible(host, port, timeout=1.0):
                    frontend_ready = True
                    print(f"{Colors.GREEN}Frontend port {port} is ready{Colors.RESET}")
                
                if backend_ready and frontend_ready:
                    break
                
                time.sleep(1)
            
            if not backend_ready or not frontend_ready:
                if not backend_ready:
                    self.warnings.append("Backend did not become ready within timeout")
                if not frontend_ready:
                    self.warnings.append("Frontend did not become ready within timeout")
            else:
                # Give services a moment to fully initialize
                time.sleep(2)
            
            print()  # Empty line
        
        # Run health checks
        # Check backend health first - if it works, port check is non-critical
        backend_health_ok = self.check_backend_health()
        # Only fail on port check if health endpoint also failed
        self.check_backend_port(is_critical=not backend_health_ok)
        self.check_frontend_accessible()
        
        return self.checks_failed == 0
    
    def print_results(self) -> None:
        """Print health check results."""
        print()
        print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}Health Check Summary{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")
        
        print(f"Checks passed: {Colors.GREEN}{self.checks_passed}{Colors.RESET}")
        print(f"Checks failed: {Colors.RED}{self.checks_failed}{Colors.RESET}")
        print()
        
        if self.errors:
            print(f"{Colors.RED}{Colors.BOLD}[ERRORS]:{Colors.RESET}\n")
            for error in self.errors:
                print(f"  {Colors.RED}{_symbols.CROSS}{Colors.RESET} {error}")
            print()
        
        if self.warnings:
            print(f"{Colors.YELLOW}{Colors.BOLD}{_symbols.WARNING}  WARNINGS:{Colors.RESET}\n")
            for warning in self.warnings:
                print(f"  {Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} {warning}")
            print()
        
        if not self.errors and not self.warnings:
            print(f"{Colors.GREEN}{Colors.BOLD}{_symbols.SUCCESS} All health checks passed!{Colors.RESET}\n")
        elif not self.errors:
            print(f"{Colors.GREEN}{Colors.BOLD}{_symbols.SUCCESS} Health checks completed with warnings{Colors.RESET}\n")
        else:
            print(f"{Colors.RED}{Colors.BOLD}[FAIL] Health check failed{Colors.RESET}\n")
            print("Troubleshooting:")
            print("  1. Check service logs in logs/ directory")
            print("  2. Verify services are running: python tools/commands/error.sh")
            print("  3. Check prerequisites: python scripts/validate-env.py && python tools/commands/validate-prerequisites.py")
            print("  4. See docs/troubleshooting-local-startup.md for help")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Health check for JackSparrow services")
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        help="Backend API URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--frontend-url",
        default="http://localhost:3000",
        help="Frontend URL (default: http://localhost:3000)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Request timeout in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for services to become available"
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=30,
        help="Maximum seconds to wait for services (default: 30)"
    )
    
    args = parser.parse_args()
    
    checker = HealthChecker(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        timeout=args.timeout
    )
    
    if checker.check_all(wait_for_services=not args.no_wait, max_wait=args.max_wait):
        checker.print_results()
        sys.exit(0)
    else:
        checker.print_results()
        sys.exit(1)


if __name__ == "__main__":
    main()

