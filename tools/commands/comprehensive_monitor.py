#!/usr/bin/env python3
"""
Comprehensive System Monitor for JackSparrow Trading Agent

Monitors all system components in parallel, checks health endpoints,
analyzes logs for errors, and provides real-time dashboard output.
"""

import os
import sys
import time
import json
import asyncio
import threading
import platform
import signal
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

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

# Set UTF-8 encoding for Windows
if platform.system() == "Windows":
    try:
        if sys.stdout.encoding != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.encoding != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass


# ANSI color codes
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


# ASCII-safe symbols
class Symbols:
    def __init__(self):
        is_windows = platform.system() == "Windows"
        self.CHECK = "[OK]" if is_windows else "✓"
        self.CROSS = "[FAIL]" if is_windows else "✗"
        self.WARNING = "[WARN]" if is_windows else "⚠"
        self.INFO = "[INFO]" if is_windows else "ℹ"
        self.SPARKLES = "[*]" if is_windows else "✨"


_symbols = Symbols()


@dataclass
class ComponentStatus:
    """Status of a system component."""
    name: str
    status: str = "unknown"  # "up", "down", "degraded", "unknown"
    last_check: Optional[datetime] = None
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitoringConfig:
    """Configuration for monitoring."""
    backend_url: str = "http://localhost:8000"
    agent_url: str = "http://localhost:8001"
    frontend_url: str = "http://localhost:3000"
    websocket_url: str = "ws://localhost:8000/ws"
    check_interval: int = 5  # seconds
    log_check_interval: int = 10  # seconds
    max_monitoring_duration: int = 1800  # 30 minutes
    timeout: float = 10.0
    start_services: bool = True


class ComprehensiveMonitor:
    """Comprehensive system monitor."""

    def __init__(self, config: MonitoringConfig):
        self.config = config
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(seconds=config.max_monitoring_duration)
        self.components: Dict[str, ComponentStatus] = {}
        self.error_counts: Dict[str, int] = {}
        self.warning_counts: Dict[str, int] = {}
        self.log_errors: List[Dict[str, Any]] = []
        self.log_warnings: List[Dict[str, Any]] = []
        self.monitoring_active = True
        self.services_started = False
        self.executor = ThreadPoolExecutor(max_workers=10)
        self._shutdown_event = threading.Event()

        # Initialize component statuses
        self._init_components()

    def _init_components(self):
        """Initialize component status tracking."""
        components = [
            "backend_api", "backend_websocket", "agent_service", "agent_feature_server",
            "frontend_app", "database", "redis", "market_data_service",
            "feature_engineering", "model_discovery", "risk_manager",
            "state_machine", "reasoning_engine", "execution_engine",
            "learning_system", "event_bus", "websocket_connections"
        ]

        for component in components:
            self.components[component] = ComponentStatus(name=component)

    def start_services_if_needed(self) -> bool:
        """Start services using start_parallel.py if not running."""
        if not self.config.start_services:
            print(f"{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Skipping service startup (start_services=False)")
            return True

        print(f"{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Checking if services are running...")

        # Check if services are already running
        if self._check_services_running():
            print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Services are already running")
            return True

        print(f"{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Starting services using start_parallel.py...")

        try:
            start_script = project_root / "tools" / "commands" / "start_parallel.py"
            if not start_script.exists():
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} start_parallel.py not found at {start_script}")
                return False

            # Start services in background
            process = subprocess.Popen(
                [sys.executable, str(start_script)],
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Wait for services to start (up to 60 seconds)
            print(f"{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Waiting for services to start...")
            start_wait_time = time.time()
            max_wait = 60

            while time.time() - start_wait_time < max_wait:
                if self._check_services_running():
                    self.services_started = True
                    print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Services started successfully")
                    return True
                time.sleep(2)

            # If we get here, services didn't start properly
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Services failed to start within {max_wait} seconds")

            # Get process output for debugging
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                if stderr:
                    print(f"{Colors.RED}Startup stderr:{Colors.RESET}")
                    print(stderr[-1000:])  # Last 1000 chars

            return False

        except Exception as e:
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Failed to start services: {e}")
            return False

    def _check_services_running(self) -> bool:
        """Check if core services are running by testing ports."""
        checks = [
            (self.config.backend_url.replace("http://", "").split(":")[0], 8000),
            (self.config.agent_url.replace("http://", "").split(":")[0], 8001),
            (self.config.frontend_url.replace("http://", "").split(":")[0], 3000),
        ]

        passed = 0
        for host, port in checks:
            if self._check_port(host, port, timeout=1.0):
                passed += 1

        return passed >= 2  # At least backend and agent should be running

    def _check_port(self, host: str, port: int, timeout: float = 2.0) -> bool:
        """Check if a TCP port is accessible."""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def run_monitoring(self):
        """Run the comprehensive monitoring."""
        print(f"{Colors.BOLD}{Colors.CYAN}🚀 JackSparrow Comprehensive System Monitor{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: {self.config.max_monitoring_duration // 60} minutes")
        print(f"Check Interval: {self.config.check_interval}s")
        print()

        # Start services if needed
        if not self.start_services_if_needed():
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Failed to start services. Exiting.")
            return

        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            # Start monitoring threads
            monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
            log_analysis_thread = threading.Thread(target=self._log_analysis_loop, daemon=True)

            monitoring_thread.start()
            log_analysis_thread.start()

            # Main dashboard loop
            self._dashboard_loop()

        except KeyboardInterrupt:
            print(f"\n{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Monitoring interrupted by user")
        except Exception as e:
            print(f"\n{Colors.RED}{_symbols.CROSS}{Colors.RESET} Monitoring error: {e}")
        finally:
            self._shutdown()

    def _monitoring_loop(self):
        """Main monitoring loop running in background thread."""
        while not self._shutdown_event.is_set() and datetime.now() < self.end_time:
            try:
                # Run all component checks in parallel
                futures = []
                check_methods = [
                    self._check_backend_api,
                    self._check_backend_websocket,
                    self._check_agent_service,
                    self._check_frontend_app,
                    self._check_database,
                    self._check_redis,
                    self._check_websocket_connections,
                ]

                for method in check_methods:
                    future = self.executor.submit(method)
                    futures.append(future)

                # Wait for all checks to complete
                for future in as_completed(futures):
                    try:
                        future.result(timeout=self.config.timeout)
                    except Exception as e:
                        # Log check errors but don't crash monitoring
                        print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Check error: {e}", file=sys.stderr)

            except Exception as e:
                print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Monitoring loop error: {e}", file=sys.stderr)

            # Wait before next check cycle
            self._shutdown_event.wait(self.config.check_interval)

    def _log_analysis_loop(self):
        """Log analysis loop running in background thread."""
        last_log_check = 0

        while not self._shutdown_event.is_set() and datetime.now() < self.end_time:
            try:
                current_time = time.time()
                if current_time - last_log_check >= self.config.log_check_interval:
                    self._analyze_logs()
                    last_log_check = current_time

            except Exception as e:
                print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Log analysis error: {e}", file=sys.stderr)

            time.sleep(1)

    def _dashboard_loop(self):
        """Main dashboard display loop."""
        last_display = 0
        display_interval = 2  # seconds

        while not self._shutdown_event.is_set() and datetime.now() < self.end_time:
            try:
                current_time = time.time()
                if current_time - last_display >= display_interval:
                    self._display_dashboard()
                    last_display = current_time

                time.sleep(0.5)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Dashboard error: {e}", file=sys.stderr)

        # Final summary
        self._display_final_summary()

    def _display_dashboard(self):
        """Display real-time monitoring dashboard."""
        # Clear screen (Unix-like systems)
        if platform.system() != "Windows":
            print("\033[2J\033[H", end="")

        now = datetime.now()
        elapsed = now - self.start_time
        remaining = self.end_time - now

        print(f"{Colors.BOLD}{Colors.CYAN}🚀 JackSparrow System Monitor{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"Time: {now.strftime('%H:%M:%S')} | Elapsed: {str(elapsed).split('.')[0]} | Remaining: {str(remaining).split('.')[0]}")
        print()

        # Component Status Grid
        print(f"{Colors.BOLD}Component Status:{Colors.RESET}")

        status_grid = []
        for name, component in self.components.items():
            if component.status == "up":
                status_icon = f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET}"
            elif component.status == "down":
                status_icon = f"{Colors.RED}{_symbols.CROSS}{Colors.RESET}"
            elif component.status == "degraded":
                status_icon = f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET}"
            else:
                status_icon = f"{Colors.BLUE}○{Colors.RESET}"

            display_name = name.replace("_", " ").title()
            response_time = f" ({component.response_time_ms:.0f}ms)" if component.response_time_ms else ""

            status_grid.append(f"  {status_icon} {display_name}{response_time}")

        # Display in columns
        for i in range(0, len(status_grid), 3):
            row = status_grid[i:i+3]
            print(" | ".join(row + [""] * (3 - len(row))))

        print()

        # Error Summary
        total_errors = sum(self.error_counts.values())
        total_warnings = sum(self.warning_counts.values())

        print(f"{Colors.BOLD}Log Summary:{Colors.RESET}")
        print(f"  Errors: {Colors.RED}{total_errors}{Colors.RESET} | Warnings: {Colors.YELLOW}{total_warnings}{Colors.RESET}")
        print()

        # Recent Errors (last 3)
        if self.log_errors:
            print(f"{Colors.BOLD}Recent Errors:{Colors.RESET}")
            for error in self.log_errors[-3:]:
                timestamp = error.get("timestamp", "unknown")[:19]  # YYYY-MM-DD HH:MM:SS
                component = error.get("component", "unknown")
                message = error.get("message", "")[:60]
                print(f"  {Colors.RED}{timestamp}{Colors.RESET} {component}: {message}")
            print()

        # System Health Score
        health_score = self._calculate_health_score()
        if health_score >= 0.8:
            health_color = Colors.GREEN
        elif health_score >= 0.6:
            health_color = Colors.YELLOW
        else:
            health_color = Colors.RED

        print(f"{Colors.BOLD}Overall Health Score: {health_color}{health_score:.1%}{Colors.RESET}")
        print()

        # Instructions
        print(f"{Colors.DIM}Press Ctrl+C to stop monitoring{Colors.RESET}")

    def _calculate_health_score(self) -> float:
        """Calculate overall system health score."""
        total_components = len(self.components)
        if total_components == 0:
            return 0.0

        healthy_components = sum(1 for c in self.components.values() if c.status == "up")
        degraded_components = sum(1 for c in self.components.values() if c.status == "degraded")

        # Weight: healthy=1.0, degraded=0.5, down=0.0
        score = (healthy_components + degraded_components * 0.5) / total_components
        return max(0.0, min(1.0, score))

    def _display_final_summary(self):
        """Display final monitoring summary."""
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}📊 MONITORING COMPLETE - FINAL SUMMARY{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")

        total_duration = datetime.now() - self.start_time
        health_score = self._calculate_health_score()
        total_errors = sum(self.error_counts.values())
        total_warnings = sum(self.warning_counts.values())

        print(f"\n{Colors.BOLD}Session Summary:{Colors.RESET}")
        print(f"  Duration: {str(total_duration).split('.')[0]}")
        print(f"  Health Score: {Colors.GREEN if health_score >= 0.8 else Colors.YELLOW if health_score >= 0.6 else Colors.RED}{health_score:.1%}{Colors.RESET}")
        print(f"  Total Log Errors: {Colors.RED}{total_errors}{Colors.RESET}")
        print(f"  Total Log Warnings: {Colors.YELLOW}{total_warnings}{Colors.RESET}")

        print(f"\n{Colors.BOLD}Component Final Status:{Colors.RESET}")
        for name, component in self.components.items():
            display_name = name.replace("_", " ").title()
            if component.status == "up":
                status = f"{Colors.GREEN}UP{Colors.RESET}"
            elif component.status == "down":
                status = f"{Colors.RED}DOWN{Colors.RESET}"
            elif component.status == "degraded":
                status = f"{Colors.YELLOW}DEGRADED{Colors.RESET}"
            else:
                status = f"{Colors.BLUE}UNKNOWN{Colors.RESET}"

            print(f"  {display_name}: {status}")

        if total_errors > 0 or total_warnings > 0:
            print(f"\n{Colors.BOLD}⚠️  Issues Detected:{Colors.RESET}")
            if total_errors > 0:
                print(f"  {Colors.RED}• {total_errors} errors found in logs{Colors.RESET}")
            if total_warnings > 0:
                print(f"  {Colors.YELLOW}• {total_warnings} warnings found in logs{Colors.RESET}")

        print(f"\n{Colors.BOLD}✅ Monitoring completed successfully{Colors.RESET}")

    def _check_backend_api(self):
        """Check backend API health."""
        component = self.components["backend_api"]
        component.last_check = datetime.now()

        try:
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=self.config.timeout) as client:
                    start_time = time.time()
                    response = client.get(f"{self.config.backend_url}/api/v1/health")
                    response_time = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        data = response.json()
                        health_score = data.get("health_score", 0.0)

                        if health_score >= 0.8:
                            component.status = "up"
                        elif health_score >= 0.5:
                            component.status = "degraded"
                        else:
                            component.status = "down"

                        component.response_time_ms = response_time
                        component.details = data
                        component.error = None
                    else:
                        component.status = "down"
                        component.error = f"HTTP {response.status_code}"
            else:
                component.status = "unknown"
                component.error = "HTTP client not available"

        except Exception as e:
            component.status = "down"
            component.error = str(e)

    def _check_backend_websocket(self):
        """Check backend WebSocket connectivity."""
        component = self.components["backend_websocket"]
        component.last_check = datetime.now()

        try:
            # Simple TCP port check for WebSocket
            import socket
            parsed = self.config.websocket_url.replace("ws://", "").replace("wss://", "")
            host_port = parsed.split(":")
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 8000

            if self._check_port(host, port, timeout=2.0):
                component.status = "up"
                component.error = None
            else:
                component.status = "down"
                component.error = "Port not accessible"

        except Exception as e:
            component.status = "down"
            component.error = str(e)

    def _check_agent_service(self):
        """Check agent service health."""
        component = self.components["agent_service"]
        component.last_check = datetime.now()

        try:
            import asyncio
            import uuid

            import websockets

            start_time = time.time()

            async def _ws_request():
                request_id = str(uuid.uuid4())
                async with websockets.connect(self.config.websocket_url) as ws:
                    await ws.send(json.dumps({
                        "action": "command",
                        "command": "get_agent_status",
                        "request_id": request_id,
                        "parameters": {}
                    }))

                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=self.config.timeout)
                        data = json.loads(raw)
                        if data.get("type") == "response" and data.get("request_id") == request_id:
                            return data

            response_message = asyncio.run(_ws_request())
            response_time = (time.time() - start_time) * 1000

            if response_message and response_message.get("success") is True:
                data = response_message.get("data", {}) or {}
                available = data.get("available", True)
                health_status = data.get("health_status", "unknown")

                if not available or health_status in ("down", "unhealthy"):
                    component.status = "down"
                elif health_status in ("degraded", "warning"):
                    component.status = "degraded"
                else:
                    component.status = "up"

                component.response_time_ms = response_time
                component.error = None
            else:
                component.status = "down"
                component.error = "WS get_agent_status failed"

        except Exception as e:
            component.status = "down"
            component.error = str(e)

    def _check_frontend_app(self):
        """Check frontend application."""
        component = self.components["frontend_app"]
        component.last_check = datetime.now()

        try:
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=self.config.timeout, follow_redirects=True) as client:
                    start_time = time.time()
                    response = client.get(self.config.frontend_url)
                    response_time = (time.time() - start_time) * 1000

                    if response.status_code in (200, 301, 302):
                        component.status = "up"
                        component.response_time_ms = response_time
                        component.error = None
                    else:
                        component.status = "down"
                        component.error = f"HTTP {response.status_code}"
            else:
                # Fallback: check port
                if self._check_port("localhost", 3000, timeout=2.0):
                    component.status = "up"
                    component.error = None
                else:
                    component.status = "down"
                    component.error = "Port not accessible"

        except Exception as e:
            component.status = "down"
            component.error = str(e)

    def _check_database(self):
        """Check database connectivity via backend health."""
        component = self.components["database"]
        component.last_check = datetime.now()

        # Database status comes from backend health endpoint
        backend_health = self.components.get("backend_api")
        if backend_health and backend_health.details:
            services = backend_health.details.get("services", {})
            db_status = services.get("database", {})

            if db_status.get("status") == "up":
                component.status = "up"
                component.error = None
            elif db_status.get("status") == "down":
                component.status = "down"
                component.error = db_status.get("error", "Database down")
            else:
                component.status = "unknown"
        else:
            component.status = "unknown"
            component.error = "Backend health not available"

    def _check_redis(self):
        """Check Redis connectivity via backend health."""
        component = self.components["redis"]
        component.last_check = datetime.now()

        # Redis status comes from backend health endpoint
        backend_health = self.components.get("backend_api")
        if backend_health and backend_health.details:
            services = backend_health.details.get("services", {})
            redis_status = services.get("redis", {})

            if redis_status.get("status") == "up":
                component.status = "up"
                component.error = None
            elif redis_status.get("status") == "down":
                component.status = "down"
                component.error = redis_status.get("error", "Redis down")
            else:
                component.status = "unknown"
        else:
            component.status = "unknown"
            component.error = "Backend health not available"

    def _check_websocket_connections(self):
        """Check WebSocket connections status."""
        component = self.components["websocket_connections"]
        component.last_check = datetime.now()

        # WebSocket status comes from backend health
        backend_health = self.components.get("backend_api")
        if backend_health and backend_health.details:
            websocket_info = backend_health.details.get("websocket", {})

            if websocket_info.get("connections", 0) > 0:
                component.status = "up"
                component.details = websocket_info
                component.error = None
            else:
                component.status = "degraded"
                component.error = "No active connections"
        else:
            component.status = "unknown"
            component.error = "Backend health not available"

    def _analyze_logs(self):
        """Analyze log files for errors and warnings."""
        log_dirs = [
            project_root / "logs" / "backend",
            project_root / "logs" / "agent",
            project_root / "logs" / "frontend"
        ]

        for log_dir in log_dirs:
            if not log_dir.exists():
                continue

            for log_file in log_dir.glob("*.log"):
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        # Read last 100 lines to avoid processing entire file each time
                        lines = f.readlines()[-100:]

                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue

                            try:
                                # Try to parse as JSON (structured logs)
                                log_entry = json.loads(line)
                                level = log_entry.get("level", "").upper()
                                component = log_entry.get("service", "unknown")

                                if level in ("ERROR", "CRITICAL", "FATAL"):
                                    if not any(e.get("message") == log_entry.get("message") and
                                             e.get("timestamp") == log_entry.get("timestamp")
                                             for e in self.log_errors[-10:]):  # Avoid duplicates
                                        self.log_errors.append(log_entry)
                                        self.error_counts[component] = self.error_counts.get(component, 0) + 1

                                elif level == "WARNING":
                                    if not any(w.get("message") == log_entry.get("message") and
                                             w.get("timestamp") == log_entry.get("timestamp")
                                             for w in self.log_warnings[-10:]):  # Avoid duplicates
                                        self.log_warnings.append(log_entry)
                                        self.warning_counts[component] = self.warning_counts.get(component, 0) + 1

                            except json.JSONDecodeError:
                                # Not JSON, check for plain text error patterns
                                if any(pattern in line.upper() for pattern in ["ERROR", "EXCEPTION", "TRACEBACK", "CRITICAL"]):
                                    if not any(e.get("message") == line for e in self.log_errors[-5:]):
                                        self.log_errors.append({
                                            "timestamp": datetime.now().isoformat(),
                                            "service": log_file.stem,
                                            "level": "ERROR",
                                            "message": line[:200]
                                        })
                                        self.error_counts[log_file.stem] = self.error_counts.get(log_file.stem, 0) + 1

                except Exception as e:
                    # Skip files that can't be read
                    continue

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\n{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Shutdown signal received")
        self._shutdown_event.set()

    def _shutdown(self):
        """Clean shutdown of monitoring."""
        self.monitoring_active = False
        self.executor.shutdown(wait=True)
        print(f"\n{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Monitoring shutdown complete")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Comprehensive system monitoring for JackSparrow")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--agent-url", default="http://localhost:8001", help="Agent service URL")
    parser.add_argument("--frontend-url", default="http://localhost:3000", help="Frontend URL")
    parser.add_argument("--websocket-url", default="ws://localhost:8000/ws", help="WebSocket URL")
    parser.add_argument("--check-interval", type=int, default=5, help="Component check interval (seconds)")
    parser.add_argument("--log-check-interval", type=int, default=10, help="Log analysis interval (seconds)")
    parser.add_argument("--duration", type=int, default=1800, help="Monitoring duration (seconds)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout (seconds)")
    parser.add_argument("--no-start-services", action="store_true", help="Don't start services automatically")

    args = parser.parse_args()

    config = MonitoringConfig(
        backend_url=args.backend_url,
        agent_url=args.agent_url,
        frontend_url=args.frontend_url,
        websocket_url=args.websocket_url,
        check_interval=args.check_interval,
        log_check_interval=args.log_check_interval,
        max_monitoring_duration=args.duration,
        timeout=args.timeout,
        start_services=not args.no_start_services
    )

    monitor = ComprehensiveMonitor(config)
    monitor.run_monitoring()


if __name__ == "__main__":
    main()