#!/usr/bin/env python3
"""
Enhanced Continuous System Monitoring Script for JackSparrow Trading Agent

Monitors all system components, logs, and performance metrics.
Provides real-time dashboard and comprehensive health assessment.
"""

import os
import sys
import time
import json
import socket
import platform
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

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

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from tools.commands.health_check import HealthChecker, Colors, _symbols


class EnhancedSystemMonitor:
    """Enhanced continuous system monitor with comprehensive component checks."""

    def __init__(self, interval: int = 30, backend_url: str = "http://localhost:8000",
                 frontend_url: str = "http://localhost:3000", agent_url: str = "http://localhost:8001",
                 websocket_url: str = "ws://localhost:8000/ws"):
        """Initialize enhanced system monitor.

        Args:
            interval: Monitoring interval in seconds
            backend_url: Backend API URL
            frontend_url: Frontend URL
            agent_url: Agent service URL
            websocket_url: WebSocket URL
        """
        self.interval = interval
        self.backend_url = backend_url.rstrip('/')
        self.frontend_url = frontend_url.rstrip('/')
        self.agent_url = agent_url.rstrip('/')
        self.websocket_url = websocket_url

        self.health_checker = HealthChecker(backend_url=backend_url, frontend_url=frontend_url)
        self.metrics: List[Dict] = []
        self.alerts: List[Dict] = []
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.warning_counts: Dict[str, int] = defaultdict(int)
        self.component_history: Dict[str, List[Dict]] = defaultdict(list)

        # Log monitoring
        self.log_errors: List[Dict] = []
        self.log_warnings: List[Dict] = []
        self.last_log_check = 0
        self.log_check_interval = 60  # Check logs every minute

        # Performance tracking
        self.performance_metrics: Dict[str, List[float]] = defaultdict(list)

    def check_system_health(self) -> Dict:
        """Check comprehensive system health across all components."""
        timestamp = datetime.now()

        # Run all component checks in parallel
        health_status = {
            "timestamp": timestamp.isoformat(),
            "backend": self._check_backend(),
            "frontend": self._check_frontend(),
            "agent": self._check_agent(),
            "feature_server": self._check_feature_server(),
            "database": self._check_database(),
            "redis": self._check_redis(),
            "websocket": self._check_websocket(),
            "market_data": self._check_market_data(),
            "models": self._check_models(),
            "system_resources": self._check_system_resources(),
        }

        # Store metrics
        self.metrics.append(health_status)

        # Keep only last 200 metrics for better trend analysis
        if len(self.metrics) > 200:
            self.metrics.pop(0)

        # Update component history
        for component, status in health_status.items():
            if component != "timestamp":
                self.component_history[component].append({
                    "timestamp": timestamp,
                    "status": status
                })
                # Keep only last 50 entries per component
                if len(self.component_history[component]) > 50:
                    self.component_history[component].pop(0)

        return health_status

    def _check_backend(self) -> Dict:
        """Check backend health with detailed metrics."""
        try:
            start_time = time.time()
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(f"{self.backend_url}/api/v1/health")
                    response_time = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        data = response.json()
                        health_score = data.get("health_score", 0.0)
                        services = data.get("services", {})

                        status = "up" if health_score >= 0.8 else "degraded" if health_score >= 0.5 else "down"

                        return {
                            "status": status,
                            "response_time_ms": round(response_time, 2),
                            "health_score": health_score,
                            "services": services
                        }
            elif REQUESTS_AVAILABLE:
                import requests
                response = requests.get(f"{self.backend_url}/api/v1/health", timeout=10.0)
                response_time = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    data = response.json()
                    health_score = data.get("health_score", 0.0)
                    status = "up" if health_score >= 0.8 else "degraded" if health_score >= 0.5 else "down"

                    return {
                        "status": status,
                        "response_time_ms": round(response_time, 2),
                        "health_score": health_score
                    }
        except Exception as e:
            return {"status": "down", "error": str(e)}

        return {"status": "unknown"}

    def _check_frontend(self) -> Dict:
        """Check frontend health."""
        try:
            start_time = time.time()
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                    response = client.get(self.frontend_url)
                    response_time = (time.time() - start_time) * 1000

                    if response.status_code in (200, 301, 302):
                        return {
                            "status": "up",
                            "response_time_ms": round(response_time, 2)
                        }
            elif REQUESTS_AVAILABLE:
                import requests
                response = requests.get(self.frontend_url, timeout=10.0, allow_redirects=True)
                response_time = (time.time() - start_time) * 1000

                if response.status_code in (200, 301, 302):
                    return {
                        "status": "up",
                        "response_time_ms": round(response_time, 2)
                    }
        except Exception as e:
            return {"status": "down", "error": str(e)}

        return {"status": "unknown"}

    def _check_agent(self) -> Dict:
        """Check agent health and status."""
        try:
            start_time = time.time()
            import asyncio
            import uuid

            import websockets

            async def _ws_request():
                request_id = str(uuid.uuid4())
                async with websockets.connect(self.websocket_url) as ws:
                    await ws.send(json.dumps({
                        "action": "command",
                        "command": "get_agent_status",
                        "request_id": request_id,
                        "parameters": {}
                    }))

                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                        data = json.loads(raw)
                        if data.get("type") == "response" and data.get("request_id") == request_id:
                            return data

            response_message = asyncio.run(_ws_request())
            response_time = (time.time() - start_time) * 1000

            if response_message and response_message.get("success") is True:
                data = response_message.get("data", {})
                state = data.get("state", "unknown")
                available = data.get("available", True)
                health_status = data.get("health_status", "unknown")

                if not available or health_status in ("down", "unhealthy", "DEGRADED"):
                    status = "down"
                elif health_status in ("degraded", "warning") or state in ("DEGRADED",):
                    status = "degraded"
                else:
                    status = "up"

                return {
                    "status": status,
                    "response_time_ms": round(response_time, 2),
                    "state": state,
                    "model_count": data.get("model_count", 0),
                }
        except Exception as e:
            return {"status": "down", "error": str(e)}

        return {"status": "unknown"}

    def _check_feature_server(self) -> Dict:
        """Check feature server health."""
        try:
            start_time = time.time()
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(f"{self.agent_url}/health")
                    response_time = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        return {
                            "status": "up",
                            "response_time_ms": round(response_time, 2)
                        }
            elif REQUESTS_AVAILABLE:
                import requests
                response = requests.get(f"{self.agent_url}/health", timeout=10.0)
                response_time = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    return {
                        "status": "up",
                        "response_time_ms": round(response_time, 2)
                    }
        except Exception as e:
            return {"status": "down", "error": str(e)}

        return {"status": "unknown"}

    def _check_database(self) -> Dict:
        """Check database connectivity via backend health."""
        backend_status = self.metrics[-1].get("backend", {}) if self.metrics else {}
        services = backend_status.get("services", {})

        db_status = services.get("database", {})
        if db_status.get("status") == "up":
            return {"status": "up"}
        elif db_status.get("status") == "down":
            return {"status": "down", "error": db_status.get("error", "Database down")}

        return {"status": "unknown"}

    def _check_redis(self) -> Dict:
        """Check Redis connectivity via backend health."""
        backend_status = self.metrics[-1].get("backend", {}) if self.metrics else {}
        services = backend_status.get("services", {})

        redis_status = services.get("redis", {})
        if redis_status.get("status") == "up":
            return {"status": "up"}
        elif redis_status.get("status") == "down":
            return {"status": "down", "error": redis_status.get("error", "Redis down")}

        return {"status": "unknown"}

    def _check_websocket(self) -> Dict:
        """Check WebSocket connection status."""
        backend_status = self.metrics[-1].get("backend", {}) if self.metrics else {}
        websocket_info = backend_status.get("websocket", {})

        connections = websocket_info.get("connections", 0)
        if connections > 0:
            return {
                "status": "up",
                "connections": connections,
                "active_channels": websocket_info.get("active_channels", [])
            }
        else:
            return {"status": "degraded", "connections": 0}

        return {"status": "unknown"}

    def _check_market_data(self) -> Dict:
        """Check market data ingestion status."""
        try:
            import asyncio
            import uuid

            import websockets

            async def _ws_request():
                request_id = str(uuid.uuid4())
                async with websockets.connect(self.websocket_url) as ws:
                    await ws.send(json.dumps({
                        "action": "command",
                        "command": "get_ticker",
                        "request_id": request_id,
                        "parameters": {"symbol": "BTCUSD"}
                    }))

                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                        data = json.loads(raw)
                        if data.get("type") == "response" and data.get("request_id") == request_id:
                            return data

            response_message = asyncio.run(_ws_request())
            if response_message and response_message.get("success") is True:
                ticker = response_message.get("data", {}) or {}
                last_update = ticker.get("timestamp")

                if last_update:
                    last_update_dt = None
                    if isinstance(last_update, str):
                        try:
                            last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                        except Exception:
                            last_update_dt = None
                    elif isinstance(last_update, (int, float)):
                        # Heuristic: epoch ms vs seconds
                        epoch = last_update / 1000 if last_update > 1e12 else last_update
                        try:
                            last_update_dt = datetime.fromtimestamp(epoch)
                        except Exception:
                            last_update_dt = None

                    if last_update_dt:
                        age_seconds = (datetime.now() - last_update_dt.replace(tzinfo=None)).total_seconds()
                        if age_seconds < 300:
                            return {
                                "status": "up",
                                "last_update": str(last_update),
                                "age_seconds": int(age_seconds),
                            }
                        return {
                            "status": "degraded",
                            "last_update": str(last_update),
                            "age_seconds": int(age_seconds),
                            "error": "Stale market data",
                        }
        except Exception as e:
            return {"status": "down", "error": str(e)}

        return {"status": "unknown"}

    def _check_models(self) -> Dict:
        """Check ML model availability."""
        try:
            if HTTPX_AVAILABLE:
                import httpx
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(f"{self.backend_url}/api/v1/models/status")
                    if response.status_code == 200:
                        data = response.json()
                        model_count = data.get("total_models", 0)
                        healthy_models = data.get("healthy_models", 0)

                        if healthy_models > 0:
                            health_ratio = healthy_models / model_count if model_count > 0 else 0
                            status = "up" if health_ratio >= 0.8 else "degraded"
                            return {
                                "status": status,
                                "total_models": model_count,
                                "healthy_models": healthy_models,
                                "health_ratio": health_ratio
                            }
                        else:
                            return {"status": "down", "error": "No healthy models"}
        except Exception as e:
            return {"status": "down", "error": str(e)}

        return {"status": "unknown"}

    def _check_system_resources(self) -> Dict:
        """Check system resource usage."""
        if not PSUTIL_AVAILABLE:
            return {"status": "unknown", "note": "psutil not available"}

        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Define thresholds
            high_cpu = cpu_percent > 80
            high_memory = memory.percent > 80
            low_disk = disk.percent > 90

            issues = []
            if high_cpu:
                issues.append("High CPU usage")
            if high_memory:
                issues.append("High memory usage")
            if low_disk:
                issues.append("Low disk space")

            status = "degraded" if issues else "up"

            return {
                "status": status,
                "cpu_percent": round(cpu_percent, 1),
                "memory_percent": round(memory.percent, 1),
                "disk_percent": round(disk.percent, 1),
                "issues": issues
            }
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    def check_alerts(self, health_status: Dict) -> List[str]:
        """Check for alert conditions and generate alerts."""
        alerts = []

        # Core service alerts
        if health_status["backend"]["status"] == "down":
            alerts.append({"level": "critical", "message": "Backend service is down", "component": "backend"})
        elif health_status["backend"]["status"] == "degraded":
            alerts.append({"level": "warning", "message": "Backend service is degraded", "component": "backend"})

        if health_status["agent"]["status"] == "down":
            alerts.append({"level": "critical", "message": "Agent service is down", "component": "agent"})
        elif health_status["agent"]["status"] == "degraded":
            alerts.append({"level": "warning", "message": "Agent service is degraded", "component": "agent"})

        if health_status["frontend"]["status"] == "down":
            alerts.append({"level": "high", "message": "Frontend service is down", "component": "frontend"})

        # Infrastructure alerts
        if health_status["database"]["status"] == "down":
            alerts.append({"level": "critical", "message": "Database is down", "component": "database"})

        if health_status["redis"]["status"] == "down":
            alerts.append({"level": "high", "message": "Redis is down", "component": "redis"})

        # Trading system alerts
        if health_status["models"]["status"] == "down":
            alerts.append({"level": "high", "message": "No healthy ML models available", "component": "models"})
        elif health_status["models"]["status"] == "degraded":
            alerts.append({"level": "warning", "message": "Some ML models are unhealthy", "component": "models"})

        if health_status["market_data"]["status"] in ["down", "degraded"]:
            alerts.append({"level": "high", "message": "Market data issues detected", "component": "market_data"})

        # System resource alerts
        system_resources = health_status.get("system_resources", {})
        if system_resources.get("status") == "degraded":
            issues = system_resources.get("issues", [])
            for issue in issues:
                alerts.append({"level": "warning", "message": f"System resource issue: {issue}", "component": "system"})

        # Store alerts
        self.alerts.extend(alerts)

        # Print immediate alerts
        for alert in alerts:
            level_color = {
                "critical": Colors.RED,
                "high": Colors.RED,
                "warning": Colors.YELLOW,
                "info": Colors.BLUE
            }.get(alert["level"], Colors.YELLOW)

            print(f"{level_color}{_symbols.WARNING} ALERT [{alert['level'].upper()}]: {alert['message']}{Colors.RESET}")

        return alerts

    def check_logs(self):
        """Check log files for errors and warnings."""
        current_time = time.time()
        if current_time - self.last_log_check < self.log_check_interval:
            return

        self.last_log_check = current_time

        # Log directories to check
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
                    # Read last 50 lines to avoid processing entire file
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()[-50:]

                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            # Try JSON parsing for structured logs
                            log_entry = json.loads(line)
                            level = log_entry.get("level", "").upper()
                            service = log_entry.get("service", log_file.stem)

                            if level in ("ERROR", "CRITICAL", "FATAL"):
                                # Avoid duplicates
                                if not any(e.get("message") == log_entry.get("message") and
                                         e.get("timestamp") == log_entry.get("timestamp")
                                         for e in self.log_errors[-10:]):
                                    self.log_errors.append(log_entry)
                                    self.error_counts[service] += 1

                            elif level == "WARNING":
                                if not any(w.get("message") == log_entry.get("message") and
                                         w.get("timestamp") == log_entry.get("timestamp")
                                         for w in self.log_warnings[-10:]):
                                    self.log_warnings.append(log_entry)
                                    self.warning_counts[service] += 1

                        except json.JSONDecodeError:
                            # Plain text log parsing
                            if any(pattern in line.upper() for pattern in ["ERROR", "EXCEPTION", "TRACEBACK", "CRITICAL"]):
                                if not any(e.get("raw_line") == line for e in self.log_errors[-5:]):
                                    self.log_errors.append({
                                        "timestamp": datetime.now().isoformat(),
                                        "service": log_file.stem,
                                        "level": "ERROR",
                                        "message": line[:200],
                                        "raw_line": line
                                    })
                                    self.error_counts[log_file.stem] += 1

                except Exception as e:
                    # Skip problematic files
                    continue

    def print_status(self, health_status: Dict):
        """Print comprehensive status dashboard."""
        # Clear screen for better UX (Unix-like systems)
        if platform.system() != "Windows":
            print("\033[2J\033[H", end="")

        timestamp = datetime.fromisoformat(health_status["timestamp"])
        elapsed = datetime.now() - timestamp.replace(tzinfo=None) if hasattr(timestamp, 'replace') else datetime.now() - timestamp

        print(f"{Colors.BOLD}{Colors.CYAN}🚀 Enhanced System Monitor{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"Time: {timestamp.strftime('%H:%M:%S')} | Checks: {len(self.metrics)} | Log Errors: {sum(self.error_counts.values())}")

        # Core Services
        print(f"\n{Colors.BOLD}Core Services:{Colors.RESET}")
        services = [
            ("Backend API", health_status["backend"]),
            ("Agent Service", health_status["agent"]),
            ("Frontend", health_status["frontend"]),
            ("Feature Server", health_status["feature_server"])
        ]

        for name, status in services:
            status_val = status["status"]
            color = {
                "up": Colors.GREEN,
                "degraded": Colors.YELLOW,
                "down": Colors.RED,
                "unknown": Colors.BLUE
            }.get(status_val, Colors.BLUE)

            symbol = {
                "up": _symbols.CHECK,
                "degraded": "⚠",
                "down": _symbols.CROSS,
                "unknown": "○"
            }.get(status_val, "○")

            response_time = f" ({status.get('response_time_ms', 0):.0f}ms)" if 'response_time_ms' in status else ""
            print(f"  {color}{symbol}{Colors.RESET} {name}: {status_val}{response_time}")

        # Infrastructure
        print(f"\n{Colors.BOLD}Infrastructure:{Colors.RESET}")
        infra = [
            ("Database", health_status["database"]),
            ("Redis", health_status["redis"]),
            ("WebSocket", health_status["websocket"])
        ]

        for name, status in infra:
            status_val = status["status"]
            color = {
                "up": Colors.GREEN,
                "degraded": Colors.YELLOW,
                "down": Colors.RED,
                "unknown": Colors.BLUE
            }.get(status_val, Colors.BLUE)

            symbol = {
                "up": _symbols.CHECK,
                "degraded": "⚠",
                "down": _symbols.CROSS,
                "unknown": "○"
            }.get(status_val, "○")

            extra_info = ""
            if name == "WebSocket" and status_val == "up":
                extra_info = f" ({status.get('connections', 0)} connections)"
            elif name == "Database" and status_val == "up":
                extra_info = " (connected)"

            print(f"  {color}{symbol}{Colors.RESET} {name}: {status_val}{extra_info}")

        # Trading Components
        print(f"\n{Colors.BOLD}Trading Components:{Colors.RESET}")
        trading = [
            ("Market Data", health_status["market_data"]),
            ("ML Models", health_status["models"])
        ]

        for name, status in trading:
            status_val = status["status"]
            color = {
                "up": Colors.GREEN,
                "degraded": Colors.YELLOW,
                "down": Colors.RED,
                "unknown": Colors.BLUE
            }.get(status_val, Colors.BLUE)

            symbol = {
                "up": _symbols.CHECK,
                "degraded": "⚠",
                "down": _symbols.CROSS,
                "unknown": "○"
            }.get(status_val, "○")

            extra_info = ""
            if name == "ML Models" and status_val in ["up", "degraded"]:
                total = status.get("total_models", 0)
                healthy = status.get("healthy_models", 0)
                extra_info = f" ({healthy}/{total} healthy)"

            print(f"  {color}{symbol}{Colors.RESET} {name}: {status_val}{extra_info}")

        # System Resources
        sys_res = health_status.get("system_resources", {})
        if sys_res.get("status") != "unknown":
            print(f"\n{Colors.BOLD}System Resources:{Colors.RESET}")
            cpu = sys_res.get("cpu_percent", 0)
            mem = sys_res.get("memory_percent", 0)
            disk = sys_res.get("disk_percent", 0)

            cpu_color = Colors.RED if cpu > 80 else Colors.YELLOW if cpu > 60 else Colors.GREEN
            mem_color = Colors.RED if mem > 80 else Colors.YELLOW if mem > 60 else Colors.GREEN
            disk_color = Colors.RED if disk > 90 else Colors.YELLOW if disk > 80 else Colors.GREEN

            print(f"  {cpu_color}CPU:{Colors.RESET} {cpu:.1f}% | {mem_color}Memory:{Colors.RESET} {mem:.1f}% | {disk_color}Disk:{Colors.RESET} {disk:.1f}%")

        # Recent Alerts
        if self.alerts:
            print(f"\n{Colors.BOLD}Recent Alerts:{Colors.RESET}")
            for alert in self.alerts[-3:]:  # Show last 3
                level_color = {
                    "critical": Colors.RED,
                    "high": Colors.RED,
                    "warning": Colors.YELLOW,
                    "info": Colors.BLUE
                }.get(alert["level"], Colors.YELLOW)

                print(f"  {level_color}• {alert['message']}{Colors.RESET}")

        # Health Score
        health_score = self._calculate_overall_health(health_status)
        health_color = Colors.GREEN if health_score >= 0.8 else Colors.YELLOW if health_score >= 0.6 else Colors.RED
        print(f"\n{Colors.BOLD}Overall Health Score: {health_color}{health_score:.1%}{Colors.RESET}")

        print(f"\n{Colors.DIM}Press Ctrl+C to stop monitoring | Interval: {self.interval}s{Colors.RESET}")

    def _calculate_overall_health(self, health_status: Dict) -> float:
        """Calculate overall system health score."""
        total_components = 0
        healthy_components = 0

        # Weight different component types
        weights = {
            "backend": 0.25, "agent": 0.25, "frontend": 0.15, "feature_server": 0.10,
            "database": 0.10, "redis": 0.10, "websocket": 0.05, "market_data": 0.05,
            "models": 0.05, "system_resources": 0.05
        }

        total_weight = 0
        weighted_health = 0

        for component, weight in weights.items():
            if component in health_status:
                status = health_status[component]["status"]
                health_value = {"up": 1.0, "degraded": 0.5, "down": 0.0, "unknown": 0.5}.get(status, 0.5)
                weighted_health += health_value * weight
                total_weight += weight

        return weighted_health / total_weight if total_weight > 0 else 0.0

    def run(self):
        """Run enhanced continuous monitoring."""
        print(f"{Colors.BOLD}{Colors.CYAN}🚀 Enhanced JackSparrow System Monitor{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"Monitoring interval: {self.interval}s")
        print(f"Log check interval: {self.log_check_interval}s")
        print(f"Backend: {self.backend_url}")
        print(f"Frontend: {self.frontend_url}")
        print(f"Agent: {self.agent_url}")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                # Check system health
                health_status = self.check_system_health()

                # Check logs periodically
                self.check_logs()

                # Print status dashboard
                self.print_status(health_status)

                # Check for alerts
                self.check_alerts(health_status)

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print(f"\n{Colors.BLUE}{_symbols.INFO}{Colors.RESET} Monitoring stopped by user")
        except Exception as e:
            print(f"\n{Colors.RED}{_symbols.CROSS}{Colors.RESET} Monitoring error: {e}")
        finally:
            self.print_summary()

    def print_summary(self):
        """Print comprehensive monitoring summary."""
        if not self.metrics:
            return

        print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}📊 MONITORING SUMMARY{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")

        total_checks = len(self.metrics)
        total_alerts = len(self.alerts)
        total_log_errors = sum(self.error_counts.values())
        total_log_warnings = sum(self.warning_counts.values())

        print(f"\n{Colors.BOLD}Session Statistics:{Colors.RESET}")
        print(f"  Total health checks: {Colors.BLUE}{total_checks}{Colors.RESET}")
        print(f"  Total alerts generated: {Colors.RED if total_alerts > 0 else Colors.GREEN}{total_alerts}{Colors.RESET}")
        print(f"  Log errors detected: {Colors.RED if total_log_errors > 0 else Colors.GREEN}{total_log_errors}{Colors.RESET}")
        print(f"  Log warnings detected: {Colors.YELLOW if total_log_warnings > 0 else Colors.GREEN}{total_log_warnings}{Colors.RESET}")

        # Component uptime summary
        if self.component_history:
            print(f"\n{Colors.BOLD}Component Uptime Summary:{Colors.RESET}")
            for component, history in self.component_history.items():
                if not history:
                    continue

                up_count = sum(1 for h in history if h["status"]["status"] == "up")
                total_count = len(history)
                uptime_percent = (up_count / total_count) * 100 if total_count > 0 else 0

                uptime_color = Colors.GREEN if uptime_percent >= 95 else Colors.YELLOW if uptime_percent >= 80 else Colors.RED
                display_name = component.replace("_", " ").title()

                print(f"  {display_name}: {uptime_color}{uptime_percent:.1f}%{Colors.RESET} ({up_count}/{total_count})")

        # Error breakdown by service
        if self.error_counts:
            print(f"\n{Colors.BOLD}Log Errors by Service:{Colors.RESET}")
            for service, count in sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  {service}: {Colors.RED}{count}{Colors.RESET}")

        # Most recent alerts
        if self.alerts:
            print(f"\n{Colors.BOLD}Recent Alerts (last 5):{Colors.RESET}")
            for alert in self.alerts[-5:]:
                level_color = {
                    "critical": Colors.RED,
                    "high": Colors.RED,
                    "warning": Colors.YELLOW,
                    "info": Colors.BLUE
                }.get(alert["level"], Colors.YELLOW)

                timestamp = alert.get("timestamp", "unknown")
                print(f"  {level_color}[{alert['level'].upper()}]{Colors.RESET} {alert['message']}")

        print(f"\n{Colors.BOLD}✅ Monitoring session completed{Colors.RESET}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced system monitoring for JackSparrow")
    parser.add_argument("--interval", type=int, default=30, help="Monitoring interval in seconds")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--frontend-url", default="http://localhost:3000", help="Frontend URL")
    parser.add_argument("--agent-url", default="http://localhost:8001", help="Agent service URL")
    parser.add_argument("--websocket-url", default="ws://localhost:8000/ws", help="WebSocket URL")
    parser.add_argument("--log-interval", type=int, default=60, help="Log check interval in seconds")

    args = parser.parse_args()

    monitor = EnhancedSystemMonitor(
        interval=args.interval,
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        agent_url=args.agent_url,
        websocket_url=args.websocket_url
    )
    monitor.log_check_interval = args.log_interval

    monitor.run()
    monitor.log_check_interval = args.log_interval

    monitor.run()


if __name__ == "__main__":
    main()

