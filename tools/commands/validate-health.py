#!/usr/bin/env python3
"""
Enhanced health validation script.

Provides comprehensive health checks with detailed reporting.
"""

import os
import sys
import platform
from pathlib import Path

# Set UTF-8 encoding for stdout/stderr on Windows
if platform.system() == "Windows":
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass

from tools.commands.health_check import HealthChecker, Colors, _symbols


class EnhancedHealthValidator:
    """Enhanced health validator."""
    
    def __init__(self, backend_url: str = "http://localhost:8000",
                 frontend_url: str = "http://localhost:3000"):
        """Initialize enhanced health validator.
        
        Args:
            backend_url: Backend API URL
            frontend_url: Frontend URL
        """
        self.health_checker = HealthChecker(backend_url=backend_url, frontend_url=frontend_url)
        self.detailed_results = {}
    
    def run_comprehensive_checks(self, wait_for_services: bool = True, max_wait: int = 30):
        """Run comprehensive health checks.
        
        Args:
            wait_for_services: If True, wait for services to become available
            max_wait: Maximum seconds to wait for services
            
        Returns:
            True if all checks pass, False otherwise
        """
        print(f"{Colors.BOLD}Running Enhanced Health Checks...{Colors.RESET}\n")
        
        # Run standard health checks
        all_passed = self.health_checker.check_all(
            wait_for_services=wait_for_services,
            max_wait=max_wait
        )
        
        # Store detailed results
        backend_health = self.health_checker.get_backend_health_details() or {}
        backend_port = self.health_checker.backend_port_status()
        frontend_port = self.health_checker.frontend_port_status()
        agent_status = self.health_checker.check_agent_status()
        frontend_http = self.health_checker.check_frontend_accessible()
        
        self.detailed_results = {
            "backend": {
                "port": backend_port,
                "health": backend_health,
            },
            "frontend": {
                "port": frontend_port,
                "http_accessible": frontend_http,
            },
            "agent": {
                "status": agent_status,
            },
        }
        
        return all_passed
    
    def print_detailed_report(self):
        """Print detailed health report."""
        print(f"\n{Colors.BOLD}Detailed Health Report{Colors.RESET}\n")
        
        # Backend details
        backend = self.detailed_results.get("backend", {})
        backend_port = backend.get("port", {})
        backend_health = backend.get("health", {})
        backend_reachable = backend_port.get("reachable", False)
        
        backend_symbol = _symbols.CHECK if backend_reachable else _symbols.CROSS
        backend_color = Colors.GREEN if backend_reachable else Colors.RED
        
        print(f"{backend_color}{backend_symbol}{Colors.RESET} Backend:")
        if backend_port:
            print(f"  Host: {backend_port.get('host')}")
            print(f"  Port: {backend_port.get('port')}")
            print(f"  Reachable: {backend_reachable}")
        if backend_health:
            print(f"  Health Status: {backend_health.get('status', 'unknown')}")
            score = backend_health.get("health_score")
            if score is not None:
                print(f"  Health Score: {score:.2f}")
            degradation = backend_health.get("degradation_reasons") or []
            if degradation:
                print("  Degradation Reasons:")
                for reason in degradation:
                    print(f"    - {reason}")
        
        # Frontend details
        frontend = self.detailed_results.get("frontend", {})
        frontend_port = frontend.get("port", {})
        frontend_reachable = frontend_port.get("reachable", False)
        frontend_http = frontend.get("http_accessible", False)
        
        frontend_symbol = _symbols.CHECK if frontend_reachable else _symbols.CROSS
        frontend_color = Colors.GREEN if frontend_reachable else Colors.RED
        
        print(f"\n{frontend_color}{frontend_symbol}{Colors.RESET} Frontend:")
        if frontend_port:
            print(f"  Host: {frontend_port.get('host')}")
            print(f"  Port: {frontend_port.get('port')}")
            print(f"  Port Reachable: {frontend_reachable}")
        print(f"  HTTP Accessible: {frontend_http}")
        
        # Agent details
        agent = self.detailed_results.get("agent", {})
        agent_status = agent.get("status", {})
        
        if agent_status:
            agent_available = agent_status.get("available", False)
            agent_symbol = _symbols.CHECK if agent_available else _symbols.CROSS
            agent_color = Colors.GREEN if agent_available else Colors.RED
            
            print(f"\n{agent_color}{agent_symbol}{Colors.RESET} Agent:")
            print(f"  Available: {agent_available}")
            if "state" in agent_status:
                print(f"  State: {agent_status['state']}")
            if "model_count" in agent_status:
                print(f"  Models: {agent_status['model_count']}")
        
        # Summary
        print(f"\n{Colors.BOLD}Summary{Colors.RESET}")
        print(f"Checks Passed: {self.health_checker.checks_passed}")
        print(f"Checks Failed: {self.health_checker.checks_failed}")
        
        if self.health_checker.warnings:
            print(f"\n{Colors.YELLOW}Warnings:{Colors.RESET}")
            for warning in self.health_checker.warnings:
                print(f"  {_symbols.WARNING} {warning}")
        
        if self.health_checker.errors:
            print(f"\n{Colors.RED}Errors:{Colors.RESET}")
            for error in self.health_checker.errors:
                print(f"  {_symbols.CROSS} {error}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced health validation")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--frontend-url", default="http://localhost:3000", help="Frontend URL")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for services")
    parser.add_argument("--max-wait", type=int, default=30, help="Maximum wait time in seconds")
    
    args = parser.parse_args()
    
    validator = EnhancedHealthValidator(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url
    )
    
    success = validator.run_comprehensive_checks(
        wait_for_services=not args.no_wait,
        max_wait=args.max_wait
    )
    
    validator.print_detailed_report()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

