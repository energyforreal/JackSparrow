#!/usr/bin/env python3
"""
Continuous system monitoring script.

Monitors system health and alerts on issues.
"""

import os
import sys
import time
import platform
from pathlib import Path
from typing import Dict, List
from datetime import datetime

# Set UTF-8 encoding for stdout/stderr on Windows
if platform.system() == "Windows":
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
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

from tools.commands.health_check import HealthChecker, Colors, _symbols


class SystemMonitor:
    """Continuous system monitor."""
    
    def __init__(self, interval: int = 30, backend_url: str = "http://localhost:8000",
                 frontend_url: str = "http://localhost:3000"):
        """Initialize system monitor.
        
        Args:
            interval: Monitoring interval in seconds
            backend_url: Backend API URL
            frontend_url: Frontend URL
        """
        self.interval = interval
        self.health_checker = HealthChecker(backend_url=backend_url, frontend_url=frontend_url)
        self.metrics: List[Dict] = []
        self.alerts: List[str] = []
    
    def check_system_health(self) -> Dict:
        """Check current system health."""
        timestamp = datetime.now()
        
        # Run health checks
        health_status = {
            "timestamp": timestamp.isoformat(),
            "backend": self._check_backend(),
            "frontend": self._check_frontend(),
            "agent": self._check_agent(),
        }
        
        # Store metrics
        self.metrics.append(health_status)
        
        # Keep only last 100 metrics
        if len(self.metrics) > 100:
            self.metrics.pop(0)
        
        return health_status
    
    def _check_backend(self) -> Dict:
        """Check backend health."""
        try:
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(f"{self.health_checker.backend_url}/api/v1/health")
                    if response.status_code == 200:
                        return {"status": "up", "response_time_ms": response.elapsed.total_seconds() * 1000}
            elif REQUESTS_AVAILABLE:
                import requests
                response = requests.get(f"{self.health_checker.backend_url}/api/v1/health", timeout=5.0)
                if response.status_code == 200:
                    return {"status": "up", "response_time_ms": response.elapsed.total_seconds() * 1000}
        except Exception as e:
            return {"status": "down", "error": str(e)}
        
        return {"status": "unknown"}
    
    def _check_frontend(self) -> Dict:
        """Check frontend health."""
        try:
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=5.0, follow_redirects=True) as client:
                    response = client.get(self.health_checker.frontend_url)
                    if response.status_code in (200, 301, 302):
                        return {"status": "up"}
            elif REQUESTS_AVAILABLE:
                import requests
                response = requests.get(self.health_checker.frontend_url, timeout=5.0, allow_redirects=True)
                if response.status_code in (200, 301, 302):
                    return {"status": "up"}
        except Exception as e:
            return {"status": "down", "error": str(e)}
        
        return {"status": "unknown"}
    
    def _check_agent(self) -> Dict:
        """Check agent health."""
        try:
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(f"{self.health_checker.backend_url}/api/v1/agent/status")
                    if response.status_code == 200:
                        data = response.json()
                        return {"status": "up", "data": data}
        except Exception as e:
            return {"status": "down", "error": str(e)}
        
        return {"status": "unknown"}
    
    def check_alerts(self, health_status: Dict):
        """Check for alert conditions."""
        alerts = []
        
        if health_status["backend"]["status"] == "down":
            alerts.append("Backend is down")
        
        if health_status["frontend"]["status"] == "down":
            alerts.append("Frontend is down")
        
        if health_status["agent"]["status"] == "down":
            alerts.append("Agent is down")
        
        if alerts:
            self.alerts.extend(alerts)
            for alert in alerts:
                print(f"{Colors.RED}{_symbols.WARNING} ALERT: {alert}{Colors.RESET}")
        
        return alerts
    
    def print_status(self, health_status: Dict):
        """Print current status."""
        timestamp = health_status["timestamp"]
        backend_status = health_status["backend"]["status"]
        frontend_status = health_status["frontend"]["status"]
        agent_status = health_status["agent"]["status"]
        
        backend_symbol = _symbols.CHECK if backend_status == "up" else _symbols.CROSS
        frontend_symbol = _symbols.CHECK if frontend_status == "up" else _symbols.CROSS
        agent_symbol = _symbols.CHECK if agent_status == "up" else _symbols.CROSS
        
        backend_color = Colors.GREEN if backend_status == "up" else Colors.RED
        frontend_color = Colors.GREEN if frontend_status == "up" else Colors.RED
        agent_color = Colors.GREEN if agent_status == "up" else Colors.RED
        
        print(f"\n[{timestamp}] System Status:")
        print(f"  {backend_color}{backend_symbol}{Colors.RESET} Backend: {backend_status}")
        print(f"  {frontend_color}{frontend_symbol}{Colors.RESET} Frontend: {frontend_status}")
        print(f"  {agent_color}{agent_symbol}{Colors.RESET} Agent: {agent_status}")
    
    def run(self):
        """Run continuous monitoring."""
        print(f"{Colors.BOLD}Starting System Monitor (interval: {self.interval}s){Colors.RESET}")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                health_status = self.check_system_health()
                self.print_status(health_status)
                self.check_alerts(health_status)
                
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print(f"\n{Colors.BOLD}Monitoring stopped{Colors.RESET}")
            self.print_summary()
    
    def print_summary(self):
        """Print monitoring summary."""
        if not self.metrics:
            return
        
        print(f"\n{Colors.BOLD}Monitoring Summary{Colors.RESET}")
        print(f"Total checks: {len(self.metrics)}")
        
        if self.alerts:
            print(f"{Colors.RED}Total alerts: {len(self.alerts)}{Colors.RESET}")
        else:
            print(f"{Colors.GREEN}No alerts{Colors.RESET}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor system health continuously")
    parser.add_argument("--interval", type=int, default=30, help="Monitoring interval in seconds")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--frontend-url", default="http://localhost:3000", help="Frontend URL")
    
    args = parser.parse_args()
    
    monitor = SystemMonitor(
        interval=args.interval,
        backend_url=args.backend_url,
        frontend_url=args.frontend_url
    )
    
    monitor.run()


if __name__ == "__main__":
    main()

