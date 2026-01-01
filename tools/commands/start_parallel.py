#!/usr/bin/env python3
"""
Parallel Process Manager for JackSparrow Trading Agent

Starts all services (backend, agent, frontend) simultaneously and manages
their lifecycle with real-time log streaming and graceful shutdown handling.
"""

import os
import sys
import subprocess
import signal
import threading
import time
import platform
import shutil
import socket
import builtins
import json
import asyncio
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

# Try to import websockets for WebSocket monitoring
try:
    import websockets
    from websockets.client import WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None  # type: ignore

# Try to import database libraries for schema verification
try:
    from sqlalchemy import create_engine, inspect, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


def _flushed_print(*args, **kwargs):
    """Proxy print that always flushes stdout (and stderr when used)."""
    kwargs.setdefault("flush", True)
    builtins.print(*args, **kwargs)


# Ensure every existing print() call in this module flushes immediately.
print = _flushed_print  # type: ignore

# Guarantee unbuffered output for this process and its children.
os.environ.setdefault("PYTHONUNBUFFERED", "1")


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes for service identification."""
    BACKEND = "\033[94m"  # Blue
    AGENT = "\033[92m"    # Green
    FRONTEND = "\033[93m" # Yellow
    YELLOW = "\033[93m"   # Yellow (alias)
    GREEN = "\033[92m"    # Green (alias)
    ERROR = "\033[91m"    # Red
    RESET = "\033[0m"     # Reset
    BOLD = "\033[1m"


def get_safe_symbol(symbol: str, fallback: str) -> str:
    """Return symbol if platform supports Unicode, otherwise fallback."""
    if platform.system() == "Windows":
        try:
            # Try to encode the symbol to check if it's supported
            symbol.encode(sys.stdout.encoding or "utf-8")
            return symbol
        except (UnicodeEncodeError, AttributeError):
            return fallback
    return symbol


@dataclass
class ServiceConfig:
    """Configuration for a service."""
    name: str
    color: str
    command: List[str]
    cwd: Optional[Path] = None
    log_file: Optional[Path] = None
    pid_file: Optional[Path] = None
    check_delay: float = 2.0
    env: Optional[Dict[str, str]] = None  # Optional environment variables


class PaperTradingValidator:
    """Validates paper trading mode configuration."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.is_paper_mode = True
        self.verification_time: Optional[datetime] = None
        self.status_message = ""
        
    def validate_startup(self) -> Tuple[bool, str]:
        """Validate paper trading mode during startup.
        
        Returns:
            Tuple of (is_valid: bool, status_message: str)
        """
        # Check environment variable
        paper_mode_env = os.environ.get("PAPER_TRADING_MODE", "").lower()
        trading_mode_env = os.environ.get("TRADING_MODE", "").lower()
        
        # Determine paper trading mode
        if trading_mode_env:
            self.is_paper_mode = trading_mode_env != "live"
        elif paper_mode_env:
            self.is_paper_mode = paper_mode_env in ("true", "1", "yes")
        else:
            # Default to paper trading
            self.is_paper_mode = True
        
        self.verification_time = datetime.now()
        
        if self.is_paper_mode:
            self.status_message = "PAPER TRADING (Safe)"
            return True, self.status_message
        else:
            self.status_message = "LIVE TRADING (WARNING: Real trades will be executed!)"
            return False, self.status_message
    
    def get_status(self) -> Dict[str, Any]:
        """Get current paper trading status.
        
        Returns:
            Dictionary with status information
        """
        return {
            "is_paper_mode": self.is_paper_mode,
            "status_message": self.status_message,
            "verification_time": self.verification_time.isoformat() if self.verification_time else None,
        }


class WebSocketMonitor:
    """Monitors WebSocket connection and tracks message freshness."""
    
    def __init__(self, url: str, thresholds: Dict[str, int]):
        self.url = url
        self.thresholds = thresholds
        self.connected = False
        self.last_messages: Dict[str, Dict[str, Any]] = {}
        self.message_counts: Dict[str, int] = {}
        self.message_timestamps: Dict[str, List[float]] = {}
        self.freshness_scores: Dict[str, float] = {}
        # Signal-specific tracking
        self.signal_history: List[Dict[str, Any]] = []  # Track last 50 signals
        self.signal_generation_times: List[float] = []  # Track intervals between signals
        self.last_signal_time: Optional[float] = None
        self._websocket: Optional[WebSocketClientProtocol] = None
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
    def start(self):
        """Start WebSocket monitoring in background thread."""
        if not WEBSOCKETS_AVAILABLE:
            print(f"{Colors.YELLOW}[Monitoring] WebSocket monitoring disabled (websockets library not available){Colors.RESET}")
            return
        
        self._monitoring_thread = threading.Thread(target=self._run_monitor, daemon=True)
        self._monitoring_thread.start()
    
    def stop(self):
        """Stop WebSocket monitoring."""
        self._stop_event.set()
        if self._loop and self._loop.is_running() and not self._loop.is_closed():
            try:
                # Schedule close in the event loop
                asyncio.run_coroutine_threadsafe(self._close_websocket(), self._loop)
            except Exception as e:
                # Log WebSocket shutdown errors instead of silently ignoring
                print(f"{Colors.YELLOW}[Monitoring] WebSocket shutdown error: {e}{Colors.RESET}", file=sys.stderr)
    
    async def _close_websocket(self):
        """Close WebSocket connection."""
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                # Log WebSocket close errors instead of silently ignoring
                print(f"{Colors.YELLOW}[Monitoring] WebSocket close error: {e}{Colors.RESET}", file=sys.stderr)
            self._websocket = None
        self.connected = False
    
    def _run_monitor(self):
        """Run WebSocket monitor in background thread."""
        # Create new event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._monitor())
        except Exception as e:
            print(f"{Colors.ERROR}WebSocket monitor error: {e}{Colors.RESET}")
        finally:
            self._loop.close()
    
    async def _monitor(self):
        """Monitor WebSocket connection and messages."""
        max_retries = 5
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            if self._stop_event.is_set():
                return
            
            try:
                async with websockets.connect(self.url) as ws:  # type: ignore
                    self._websocket = ws
                    self.connected = True
                    
                    # Subscribe to all channels
                    subscribe_msg = json.dumps({
                        "action": "subscribe",
                        "channels": ["agent_state", "market_tick", "signal_update", 
                                   "reasoning_chain_update", "model_prediction_update", 
                                   "portfolio_update", "trade_executed", "health_update"]
                    })
                    await ws.send(subscribe_msg)
                    
                    # Monitor messages
                    async for message in ws:
                        if self._stop_event.is_set():
                            break
                        self._process_message(message)
                        
            except Exception as e:
                self.connected = False
                # Log connection failures instead of silently ignoring
                if attempt < max_retries - 1:
                    print(f"{Colors.YELLOW}[Monitoring] WebSocket connection attempt {attempt + 1}/{max_retries} failed: {e}{Colors.RESET}", file=sys.stderr)
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    # Final attempt failed, log and stop trying
                    print(f"{Colors.YELLOW}[Monitoring] WebSocket monitor failed after {max_retries} attempts: {e}{Colors.RESET}", file=sys.stderr)
                    break
    
    def _process_message(self, message: str):
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")
            
            # Track message count
            self.message_counts[msg_type] = self.message_counts.get(msg_type, 0) + 1
            
            # Extract timestamps
            server_ts_ms = data.get("server_timestamp_ms")
            data_ts = data.get("data", {}).get("timestamp")
            
            current_time_ms = int(time.time() * 1000)
            current_time = time.time()
            
            # Calculate age
            age_ms = None
            if server_ts_ms:
                age_ms = current_time_ms - server_ts_ms
            elif data_ts:
                try:
                    ts_dt = datetime.fromisoformat(data_ts.replace("Z", "+00:00"))
                    ts_ms = int(ts_dt.timestamp() * 1000)
                    age_ms = current_time_ms - ts_ms
                except Exception:
                    pass
            
            # Store message info
            self.last_messages[msg_type] = {
                "type": msg_type,
                "age_ms": age_ms,
                "age_seconds": age_ms / 1000.0 if age_ms else None,
                "timestamp": datetime.now().isoformat(),
                "server_timestamp_ms": server_ts_ms,
            }
            
            # Signal-specific tracking
            if msg_type == "signal_update":
                signal_data = data.get("data", {})
                signal_info = {
                    "signal": signal_data.get("signal", "UNKNOWN"),
                    "confidence": signal_data.get("confidence", 0.0),
                    "timestamp": data_ts or datetime.now().isoformat(),
                    "server_timestamp_ms": server_ts_ms,
                    "age_seconds": age_ms / 1000.0 if age_ms else None,
                    "received_at": current_time,
                }
                
                # Track signal generation interval
                if self.last_signal_time is not None:
                    interval = current_time - self.last_signal_time
                    self.signal_generation_times.append(interval)
                    # Keep only last 50 intervals
                    if len(self.signal_generation_times) > 50:
                        self.signal_generation_times.pop(0)
                
                self.last_signal_time = current_time
                
                # Add to signal history
                self.signal_history.append(signal_info)
                # Keep only last 50 signals
                if len(self.signal_history) > 50:
                    self.signal_history.pop(0)
            
            # Track timestamps for freshness calculation
            if age_ms is not None:
                if msg_type not in self.message_timestamps:
                    self.message_timestamps[msg_type] = []
                self.message_timestamps[msg_type].append(age_ms)
                # Keep only last 100 timestamps
                if len(self.message_timestamps[msg_type]) > 100:
                    self.message_timestamps[msg_type].pop(0)
                
                # Calculate freshness score
                self._calculate_freshness_score(msg_type)
                
        except json.JSONDecodeError:
            # JSON decode errors are expected for non-JSON messages, no need to log
            pass
        except Exception as e:
            # Log processing errors instead of silently ignoring
            print(f"{Colors.YELLOW}[Monitoring] WebSocket message processing error: {e}{Colors.RESET}", file=sys.stderr)
    
    def _calculate_freshness_score(self, msg_type: str):
        """Calculate freshness score for a message type."""
        if msg_type not in self.message_timestamps or not self.message_timestamps[msg_type]:
            return
        
        threshold_ms = self.thresholds.get(msg_type, self.thresholds.get("other", 30000)) * 1000
        ages = self.message_timestamps[msg_type]
        
        if not ages:
            return
        
        # Score based on how many messages are within threshold
        fresh_count = sum(1 for age in ages if age < threshold_ms)
        score = (fresh_count / len(ages)) * 100.0 if ages else 0.0
        
        self.freshness_scores[msg_type] = score
    
    def get_freshness_stats(self) -> Dict[str, Any]:
        """Get freshness statistics.
        
        Returns:
            Dictionary with freshness statistics
        """
        overall_freshness = 0.0
        if self.freshness_scores:
            overall_freshness = sum(self.freshness_scores.values()) / len(self.freshness_scores)
        
        stale_messages = []
        for msg_type, last_msg in self.last_messages.items():
            threshold = self.thresholds.get(msg_type, self.thresholds.get("other", 30))
            age_seconds = last_msg.get("age_seconds")
            if age_seconds and age_seconds > threshold:
                stale_messages.append(msg_type)
        
        # Calculate signal generation statistics
        signal_stats = {}
        if self.signal_generation_times:
            avg_interval = sum(self.signal_generation_times) / len(self.signal_generation_times)
            signal_stats = {
                "total_signals": len(self.signal_history),
                "average_interval_seconds": avg_interval,
                "min_interval_seconds": min(self.signal_generation_times),
                "max_interval_seconds": max(self.signal_generation_times),
                "last_signal_age_seconds": time.time() - self.last_signal_time if self.last_signal_time else None,
            }
            # Calculate expected frequency (signals per hour)
            if signal_stats["average_interval_seconds"] > 0:
                signals_per_hour = 3600.0 / signal_stats["average_interval_seconds"]
                signal_stats["signals_per_hour"] = signals_per_hour
            else:
                signal_stats["signals_per_hour"] = 0.0
        else:
            signal_stats = {
                "total_signals": len(self.signal_history),
                "average_interval_seconds": None,
                "signals_per_hour": None,
                "last_signal_age_seconds": time.time() - self.last_signal_time if self.last_signal_time else None,
            }
        
        # Get last signal info
        last_signal = None
        if self.signal_history:
            last_signal = self.signal_history[-1]
        
        return {
            "connected": self.connected,
            "overall_freshness": overall_freshness,
            "stale_messages": stale_messages,
            "message_counts": dict(self.message_counts),
            "freshness_scores": dict(self.freshness_scores),
            "signal_stats": signal_stats,
            "last_signal": last_signal,
        }
    
    def get_last_messages(self) -> Dict[str, Dict[str, Any]]:
        """Get last received messages per type.
        
        Returns:
            Dictionary mapping message type to last message info
        """
        return dict(self.last_messages)


class MonitoringDashboard:
    """Real-time monitoring dashboard."""
    
    def __init__(self, services: Dict[str, "ServiceManager"], paper_validator: PaperTradingValidator, 
                 ws_monitor: Optional[WebSocketMonitor], refresh_interval: float = 2.0,
                 clear_screen: bool = False):
        self.services = services
        self.paper_validator = paper_validator
        self.ws_monitor = ws_monitor
        self.refresh_interval = refresh_interval
        self.clear_screen = clear_screen
        self._running = False
        self._dashboard_thread: Optional[threading.Thread] = None
        
    def start(self):
        """Start dashboard rendering thread."""
        self._running = True
        self._dashboard_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._dashboard_thread.start()
    
    def stop(self):
        """Stop dashboard rendering."""
        self._running = False
    
    def _render_loop(self):
        """Dashboard rendering loop."""
        while self._running:
            try:
                self.render()
                time.sleep(self.refresh_interval)
            except Exception as e:
                # Log dashboard render errors instead of silently continuing
                print(f"{Colors.YELLOW}[Dashboard] Render error: {e}{Colors.RESET}", file=sys.stderr)
                time.sleep(self.refresh_interval)
    
    def render(self):
        """Render the monitoring dashboard."""
        if self.clear_screen:
            # Clear screen (works on most terminals)
            print("\033[2J\033[H", end="")
        
        # Dashboard header
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}JackSparrow Monitoring Dashboard    Last Update: {now}{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        
        # Service Status
        print(f"\n{Colors.BOLD}Service Status{Colors.RESET}")
        for name, manager in self.services.items():
            status = "Running" if manager.is_alive() else "Stopped"
            symbol = "OK" if manager.is_alive() else "X"
            if platform.system() != "Windows":
                symbol = "✓" if manager.is_alive() else "✗"
            color = Colors.GREEN if manager.is_alive() else Colors.ERROR
            print(f"  {color}{symbol}{Colors.RESET} {name}: {status}")
        
        # Paper Trading Status
        paper_status = self.paper_validator.get_status()
        print(f"\n{Colors.BOLD}Paper Trading{Colors.RESET}")
        if paper_status["is_paper_mode"]:
            symbol = "OK" if platform.system() == "Windows" else "✓"
            print(f"  {Colors.GREEN}{symbol}{Colors.RESET} ENABLED ({paper_status['status_message']})")
        else:
            symbol = "X" if platform.system() == "Windows" else "✗"
            print(f"  {Colors.ERROR}{symbol}{Colors.RESET} DISABLED - {Colors.ERROR}LIVE TRADING MODE{Colors.RESET}")
        
        # Data Freshness
        if self.ws_monitor:
            print(f"\n{Colors.BOLD}Data Freshness{Colors.RESET}")
            stats = self.ws_monitor.get_freshness_stats()
            last_messages = self.ws_monitor.get_last_messages()
            
            ws_status = "Connected" if stats["connected"] else "Disconnected"
            ws_symbol = "OK" if stats["connected"] else "X"
            if platform.system() != "Windows":
                ws_symbol = "✓" if stats["connected"] else "✗"
            ws_color = Colors.GREEN if stats["connected"] else Colors.ERROR
            print(f"  {ws_color}{ws_symbol}{Colors.RESET} WebSocket: {ws_status}")
            
            if stats["connected"] and last_messages:
                # Show freshness for each message type
                for msg_type in ["agent_state", "market_tick", "signal_update", "reasoning_chain_update"]:
                    if msg_type in last_messages:
                        msg_info = last_messages[msg_type]
                        age_seconds = msg_info.get("age_seconds")
                        threshold = self.ws_monitor.thresholds.get(msg_type, self.ws_monitor.thresholds.get("other", 30))
                        
                        if age_seconds is not None:
                            age_str = f"{int(age_seconds)}s ago"
                            if age_seconds < threshold:
                                status_str = "Fresh"
                                status_color = Colors.GREEN
                                status_symbol = "OK" if platform.system() == "Windows" else "✓"
                            elif age_seconds < threshold * 2:
                                status_str = "Warning"
                                status_color = Colors.YELLOW
                                status_symbol = "!" if platform.system() == "Windows" else "⚠"
                            else:
                                status_str = f"Stale (>={threshold}s)"
                                status_color = Colors.ERROR
                                status_symbol = "X" if platform.system() == "Windows" else "✗"
                            
                            print(f"    {status_color}{status_symbol}{Colors.RESET} {msg_type}: {age_str:>10}  {status_str}")
                
                # Signal Generation Statistics
                signal_stats = stats.get("signal_stats", {})
                if signal_stats and signal_stats.get("total_signals", 0) > 0:
                    print(f"\n{Colors.BOLD}Signal Generation{Colors.RESET}")
                    total_signals = signal_stats.get("total_signals", 0)
                    avg_interval = signal_stats.get("average_interval_seconds")
                    signals_per_hour = signal_stats.get("signals_per_hour")
                    last_signal_age = signal_stats.get("last_signal_age_seconds")
                    
                    print(f"  Total Signals: {total_signals}")
                    if avg_interval is not None:
                        # Format interval display - show decimals for small intervals
                        if avg_interval < 1.0:
                            print(f"  Avg Interval: {avg_interval:.3f}s ({avg_interval/60:.3f} min)")
                        else:
                            print(f"  Avg Interval: {int(avg_interval)}s ({avg_interval/60:.1f} min)")
                    if signals_per_hour is not None:
                        # Cap unrealistic frequencies for display
                        if signals_per_hour > 1000:
                            print(f"  Frequency: >1000 signals/hour (interval too small)")
                        else:
                            print(f"  Frequency: {signals_per_hour:.1f} signals/hour")
                    if last_signal_age is not None:
                        age_min = int(last_signal_age / 60)
                        age_sec = int(last_signal_age % 60)
                        if last_signal_age < 300:  # 5 minutes
                            age_color = Colors.GREEN
                        elif last_signal_age < 900:  # 15 minutes
                            age_color = Colors.YELLOW
                        else:
                            age_color = Colors.ERROR
                        print(f"  Last Signal: {age_color}{age_min}m {age_sec}s ago{Colors.RESET}")
                    
                    # Show last signal details
                    last_signal = stats.get("last_signal")
                    if last_signal:
                        signal_type = last_signal.get("signal", "UNKNOWN")
                        confidence = last_signal.get("confidence", 0.0)
                        signal_color = Colors.GREEN if signal_type in ["BUY", "STRONG_BUY"] else Colors.ERROR if signal_type in ["SELL", "STRONG_SELL"] else Colors.YELLOW
                        print(f"  Last Signal: {signal_color}{signal_type}{Colors.RESET} (Confidence: {confidence:.1f}%)")
                
                # Overall freshness score
                freshness = stats.get("overall_freshness", 0.0)
                print(f"\n  Freshness Score: {freshness:.0f}%")
        
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")


class ValidationReporter:
    """Generates validation reports."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.logs_dir = project_root / "logs"
        self.logs_dir.mkdir(exist_ok=True)
    
    def generate_report(self, services: Dict[str, "ServiceManager"], 
                       paper_validator: PaperTradingValidator,
                       ws_monitor: Optional[WebSocketMonitor]) -> Dict[str, Any]:
        """Generate validation report.
        
        Returns:
            Dictionary with validation report data
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "paper_trading": {
                "validated": True,
                "mode": "paper" if paper_validator.is_paper_mode else "live",
                "status": paper_validator.status_message,
            },
            "data_freshness": {
                "status": "unknown",
                "average_freshness": 0.0,
                "stale_messages": [],
            },
            "service_health": {},
            "recommendations": [],
        }
        
        # Service health
        for name, manager in services.items():
            report["service_health"][name] = {
                "running": manager.is_alive(),
                "status": "healthy" if manager.is_alive() else "stopped",
            }
        
        # Data freshness
        if ws_monitor:
            stats = ws_monitor.get_freshness_stats()
            signal_stats = stats.get("signal_stats", {})
            report["data_freshness"] = {
                "status": "good" if stats["connected"] and stats["overall_freshness"] > 80 else "degraded",
                "connected": stats["connected"],
                "average_freshness": stats["overall_freshness"],
                "stale_messages": stats["stale_messages"],
                "message_counts": stats["message_counts"],
            }
            # Add signal generation statistics
            if signal_stats:
                report["signal_generation"] = {
                    "total_signals": signal_stats.get("total_signals", 0),
                    "average_interval_seconds": signal_stats.get("average_interval_seconds"),
                    "signals_per_hour": signal_stats.get("signals_per_hour"),
                    "last_signal_age_seconds": signal_stats.get("last_signal_age_seconds"),
                    "last_signal": stats.get("last_signal"),
                }
        
        # Recommendations
        if not paper_validator.is_paper_mode:
            report["recommendations"].append("WARNING: Live trading mode detected. Ensure this is intentional.")
        
        if ws_monitor and ws_monitor.connected:
            if stats["overall_freshness"] < 80:
                report["recommendations"].append("Data freshness is below optimal. Check WebSocket connection and agent activity.")
            if stats["stale_messages"]:
                report["recommendations"].append(f"Some message types are stale: {', '.join(stats['stale_messages'])}")
            
            # Signal-specific recommendations
            signal_stats = stats.get("signal_stats", {})
            if signal_stats:
                last_signal_age = signal_stats.get("last_signal_age_seconds")
                if last_signal_age is not None:
                    if last_signal_age > 1800:  # 30 minutes
                        report["recommendations"].append(f"WARNING: No signals received for {int(last_signal_age/60)} minutes. Check agent activity and candle close events.")
                    elif last_signal_age > 900:  # 15 minutes
                        report["recommendations"].append(f"CAUTION: Last signal was {int(last_signal_age/60)} minutes ago. Expected frequency: ~15 minutes.")
                
                avg_interval = signal_stats.get("average_interval_seconds")
                if avg_interval and avg_interval > 1200:  # 20 minutes
                    report["recommendations"].append(f"Signal generation interval ({int(avg_interval/60)} min) is longer than expected (15 min). Check agent configuration.")
        
        if not report["recommendations"]:
            report["recommendations"].append("System operating normally")
        
        return report
    
    def save_json(self, report: Dict[str, Any], filename: Optional[str] = None) -> Path:
        """Save report as JSON file.
        
        Returns:
            Path to saved report file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"validation_report_{timestamp}.json"
        
        report_path = self.logs_dir / filename
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        return report_path
    
    def print_summary(self, report: Dict[str, Any]):
        """Print validation report summary to console."""
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}Validation Report{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
        
        # Paper Trading
        paper = report["paper_trading"]
        symbol = "OK" if paper["validated"] and paper["mode"] == "paper" else "X"
        if platform.system() != "Windows":
            symbol = "✓" if paper["validated"] and paper["mode"] == "paper" else "✗"
        color = Colors.GREEN if paper["mode"] == "paper" else Colors.ERROR
        print(f"Paper Trading: {color}{symbol}{Colors.RESET} {'VALIDATED' if paper['validated'] else 'WARNING'}")
        print(f"  Mode: {paper['mode'].title()} Trading")
        print(f"  Status: {paper['status']}\n")
        
        # Data Freshness
        freshness = report["data_freshness"]
        if freshness.get("connected"):
            status = freshness.get("status", "unknown")
            symbol = "OK" if status == "good" else "!"
            if platform.system() != "Windows":
                symbol = "✓" if status == "good" else "⚠"
            color = Colors.GREEN if status == "good" else Colors.YELLOW
            print(f"Data Freshness: {color}{symbol}{Colors.RESET} {status.upper()}")
            print(f"  WebSocket: {'Connected' if freshness.get('connected') else 'Disconnected'}")
            print(f"  Average freshness: {freshness.get('average_freshness', 0):.0f}%")
            if freshness.get("stale_messages"):
                print(f"  Stale messages: {len(freshness['stale_messages'])} ({', '.join(freshness['stale_messages'])})")
        else:
            print(f"Data Freshness: {Colors.YELLOW}⚠{Colors.RESET} NOT MONITORED")
        print()
        
        # Service Health
        print("Service Health:")
        for name, health in report["service_health"].items():
            symbol = "OK" if health["running"] else "X"
            if platform.system() != "Windows":
                symbol = "✓" if health["running"] else "✗"
            color = Colors.GREEN if health["running"] else Colors.ERROR
            print(f"  {color}{symbol}{Colors.RESET} {name}: {health['status']}")
        print()
        
        # Recommendations
        print("Recommendations:")
        for rec in report["recommendations"]:
            print(f"  - {rec}")
        print()


class ServiceManager:
    """Manages a single service process."""
    
    def __init__(self, config: ServiceConfig, project_root: Path):
        self.config = config
        self.project_root = project_root
        self.process: Optional[subprocess.Popen] = None
        self.log_thread: Optional[threading.Thread] = None
        self.running = False
        self.error_count = 0
        self.warning_count = 0
        self.recent_errors: List[str] = []
        self.recent_warnings: List[str] = []
        self.startup_error_threshold = 5  # Fail if more than 5 errors in first 30 seconds
        self.startup_start_time: Optional[float] = None
        
    def start(self) -> bool:
        """Start the service process."""
        try:
            # Prepare command
            cmd = self.config.command
            cwd = self.config.cwd or self.project_root
            
            # Ensure log directory exists
            if self.config.log_file:
                self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Prepare environment variables
            process_env = os.environ.copy()
            if self.config.env:
                process_env.update(self.config.env)
            
            # Start process with UTF-8 encoding to handle Windows charmap issues
            self.process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',  # Replace invalid bytes instead of failing
                bufsize=1,
                universal_newlines=True,
            )
            
            # Check if process started successfully
            # Use wait(timeout=0) for immediate check instead of poll() to avoid race condition
            try:
                return_code = self.process.wait(timeout=0)
                if return_code is not None:
                    # Process exited immediately - capture error output
                    # Also capture stderr separately if available
                    try:
                        stdout, stderr = self.process.communicate(timeout=2)
                        error_msg = stdout.strip() if stdout else "Process exited immediately"
                        if stderr and stderr.strip():
                            error_msg += f"\n   stderr: {stderr.strip()[:200]}"
                    except subprocess.TimeoutExpired:
                        # Process may have output but communicate timed out
                        error_msg = "Process exited immediately (output capture timed out)"
                    except Exception as e:
                        error_msg = f"Process exited immediately (error capturing output: {e})"
                    
                    error_symbol = "X" if platform.system() == "Windows" else "✗"
                    print(f"{Colors.ERROR}{error_symbol} {self.config.name} failed to start (exit code: {return_code}): {error_msg}{Colors.RESET}")
                    return False
            except subprocess.TimeoutExpired:
                # Process is still running, which is good
                pass
            
            # Write PID file
            if self.config.pid_file:
                self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config.pid_file, 'w') as f:
                    f.write(str(self.process.pid))
            
            self.running = True
            self.startup_start_time = time.time()
            
            # Start log streaming thread
            self.log_thread = threading.Thread(
                target=self._stream_logs,
                daemon=True
            )
            self.log_thread.start()
            
            return True
            
        except subprocess.TimeoutExpired:
            # Process started but communication timed out (likely still running)
            self.running = True
            if self.config.pid_file:
                self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config.pid_file, 'w') as f:
                    f.write(str(self.process.pid))
            return True
        except FileNotFoundError:
            error_symbol = "X" if platform.system() == "Windows" else "✗"
            missing_cmd = self.config.command[0]
            print(f"{Colors.ERROR}{error_symbol} Failed to start {self.config.name}: Command not found ({missing_cmd}){Colors.RESET}")
            print(f"   Make sure {missing_cmd} is installed and in PATH")
            return False
        except Exception as e:
            error_symbol = "X" if platform.system() == "Windows" else "✗"
            print(f"{Colors.ERROR}{error_symbol} Failed to start {self.config.name}: {e}{Colors.RESET}")
            return False
    
    def _stream_logs(self):
        """Stream logs from process stdout to console and file with encoding error handling."""
        # Set UTF-8 encoding for stdout/stderr on Windows to prevent encoding errors
        if platform.system() == "Windows":
            try:
                if sys.stdout.encoding != 'utf-8':
                    sys.stdout.reconfigure(encoding='utf-8')
                if sys.stderr.encoding != 'utf-8':
                    sys.stderr.reconfigure(encoding='utf-8')
            except (AttributeError, ValueError):
                # Python < 3.7 or encoding not available, will handle errors in print statements
                pass
        
        log_file_handle = None
        if self.config.log_file:
            try:
                log_file_handle = open(self.config.log_file, 'w', encoding='utf-8', errors='replace')
            except Exception as e:
                print(f"{Colors.ERROR}Failed to open log file {self.config.log_file}: {e}{Colors.RESET}")
        
        try:
            if self.process and self.process.stdout:
                for line in iter(self.process.stdout.readline, ''):
                    if not line:
                        break
                    
                    # Ensure line is properly decoded (handle any encoding issues)
                    try:
                        # Line should already be decoded by subprocess with UTF-8, but handle edge cases
                        if isinstance(line, bytes):
                            line = line.decode('utf-8', errors='replace')
                    except (UnicodeDecodeError, AttributeError) as e:
                        # If decoding fails, replace invalid characters
                        if isinstance(line, bytes):
                            line = line.decode('utf-8', errors='replace')
                        else:
                            # If it's already a string but has encoding issues, try to sanitize
                            line = line.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    
                    # Write to log file
                    if log_file_handle:
                        try:
                            log_file_handle.write(line)
                            log_file_handle.flush()
                        except Exception as e:
                            # Log file write errors to stderr instead of silently ignoring
                            print(f"{Colors.ERROR}[{self.config.name}] Log file write error: {e}{Colors.RESET}", file=sys.stderr)
                            # Close and remove handle to prevent repeated errors
                            try:
                                log_file_handle.close()
                            except Exception:
                                pass
                            log_file_handle = None
                    
                    # Try to parse structured JSON logs for statistics
                    try:
                        # Check if line is JSON (structured log)
                        if line.strip().startswith('{'):
                            log_data = json.loads(line.strip())
                            log_level = log_data.get("level", "").upper()
                            
                            if log_level == "ERROR":
                                self.error_count += 1
                                msg = log_data.get("event", log_data.get("message", ""))
                                if msg:
                                    self.recent_errors.append(msg)
                                    if len(self.recent_errors) > 5:
                                        self.recent_errors.pop(0)
                            elif log_level == "WARNING":
                                self.warning_count += 1
                                msg = log_data.get("event", log_data.get("message", ""))
                                if msg:
                                    self.recent_warnings.append(msg)
                                    if len(self.recent_warnings) > 5:
                                        self.recent_warnings.pop(0)
                    except (json.JSONDecodeError, KeyError, AttributeError):
                        # Not JSON or missing fields, check for plain text errors/warnings
                        line_upper = line.upper()
                        if "ERROR" in line_upper or "ERR" in line_upper:
                            self.error_count += 1
                            if len(self.recent_errors) < 5:
                                self.recent_errors.append(line.strip()[:100])
                        elif "WARNING" in line_upper or "WARN" in line_upper:
                            self.warning_count += 1
                            if len(self.recent_warnings) < 5:
                                self.recent_warnings.append(line.strip()[:100])
                    
                    # Print to console with service prefix
                    prefix = f"{self.config.color}[{self.config.name}]{Colors.RESET}"
                    try:
                        # Try to print normally
                        print(f"{prefix} {line.rstrip()}")
                    except UnicodeEncodeError:
                        # Fallback: sanitize line for console output
                        try:
                            safe_line = line.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                            print(f"{prefix} {safe_line.rstrip()}")
                        except Exception:
                            # Last resort: use ASCII-safe representation
                            safe_line = repr(line)[:200] if len(line) > 200 else repr(line)
                            print(f"{prefix} [Encoding error, showing safe representation]: {safe_line}")
                    
        except Exception as e:
            error_msg = str(e)
            # Don't show encoding errors in a way that causes more encoding errors
            try:
                print(f"{Colors.ERROR}Log streaming error for {self.config.name}: {error_msg}{Colors.RESET}", file=sys.stderr)
            except UnicodeEncodeError:
                print(f"[ERROR] Log streaming error for {self.config.name}: {repr(error_msg)}", file=sys.stderr)
            # Track that log streaming failed
            self.error_count += 1
            if len(self.recent_errors) < 5:
                self.recent_errors.append(f"Log streaming failed: {error_msg[:100]}")
        finally:
            if log_file_handle:
                try:
                    log_file_handle.close()
                except Exception:
                    pass
            # Only set running to False if process is actually dead
            if not self.is_alive():
                self.running = False
    
    def is_alive(self) -> bool:
        """Check if process is still running."""
        if not self.process:
            return False
        return self.process.poll() is None
    
    def stop(self):
        """Stop the service process."""
        if not self.process:
            return
        
        self.running = False
        
        try:
            # Try graceful shutdown first
            if platform.system() == "Windows":
                self.process.terminate()
            else:
                self.process.send_signal(signal.SIGTERM)
            
            # Wait up to 5 seconds for graceful shutdown
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if still running
                self.process.kill()
                self.process.wait()
                
        except Exception as e:
            print(f"{Colors.ERROR}Error stopping {self.config.name}: {e}{Colors.RESET}")
        
        # Clean up PID file
        if self.config.pid_file and self.config.pid_file.exists():
            try:
                self.config.pid_file.unlink()
            except Exception:
                pass


class ParallelProcessManager:
    """Manages multiple services in parallel."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.services: Dict[str, ServiceManager] = {}
        self.shutdown_event = threading.Event()
        self.paper_validator: Optional[PaperTradingValidator] = None
        self.ws_monitor: Optional[WebSocketMonitor] = None
        self.dashboard: Optional[MonitoringDashboard] = None
        self.validation_reporter: Optional[ValidationReporter] = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        if platform.system() != "Windows":
            signal.signal(signal.SIGHUP, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\n{Colors.BOLD}Shutting down services...{Colors.RESET}")
        self.shutdown_event.set()
        self.stop_all()
        sys.exit(0)
    
    def add_service(self, config: ServiceConfig):
        """Add a service to manage."""
        manager = ServiceManager(config, self.project_root)
        self.services[config.name] = manager
    
    def start_all(self) -> bool:
        """Start all services simultaneously."""
        print(f"{Colors.BOLD}Starting JackSparrow Trading Agent...{Colors.RESET}\n")
        
        # Ensure logs directory exists
        logs_dir = self.project_root / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        # Start all services
        started_services = []
        failed_services = []
        error_symbol = "X" if platform.system() == "Windows" else "✗"
        for name, manager in self.services.items():
            print(f"{Colors.BOLD}Starting {name}...{Colors.RESET}")
            if manager.start():
                started_services.append(name)
            else:
                failed_services.append(name)
                print(f"{Colors.ERROR}{error_symbol} {name} failed to start{Colors.RESET}")
        
        if not started_services:
            print(f"\n{Colors.ERROR}{error_symbol} No services started successfully{Colors.RESET}")
            if failed_services:
                print(f"   Failed services: {', '.join(failed_services)}")
                print(f"   Check logs in {logs_dir} for details")
            return False
        
        # Wait a bit for processes to initialize
        max_delay = max(
            (self.services[name].config.check_delay for name in started_services),
            default=3.0
        )
        time.sleep(max_delay)
        
        # Check for excessive errors during startup
        for name in started_services:
            manager = self.services[name]
            if manager.startup_start_time:
                elapsed = time.time() - manager.startup_start_time
                if elapsed < 30 and manager.error_count > manager.startup_error_threshold:
                    error_symbol = "X" if platform.system() == "Windows" else "✗"
                    print(f"{Colors.ERROR}{error_symbol} {name} has {manager.error_count} errors in first {int(elapsed)}s (threshold: {manager.startup_error_threshold}){Colors.RESET}")
                    if manager.recent_errors:
                        print(f"   Recent errors: {', '.join(manager.recent_errors[:3])}")
                    dead_services.append(name)
        
        # Check if all started services are still alive
        alive_services = []
        dead_services = []
        error_symbol = "X" if platform.system() == "Windows" else "✗"
        for name in started_services:
            if self.services[name].is_alive():
                alive_services.append(name)
            else:
                dead_services.append(name)
                print(f"{Colors.ERROR}{error_symbol} {name} process died shortly after startup{Colors.RESET}")
                # Try to get error from log file
                log_file = self.services[name].config.log_file
                if log_file and log_file.exists():
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            if lines:
                                # Show last 5 lines instead of just last line, and don't truncate
                                last_lines = lines[-5:]
                                print(f"   Last log entries:")
                                for line in last_lines:
                                    print(f"     {line.rstrip()}")
                    except Exception as e:
                        # Log file read errors instead of silently ignoring
                        print(f"   Could not read log file: {e}", file=sys.stderr)
        
        if dead_services:
            error_symbol = "X" if platform.system() == "Windows" else "✗"
            print(f"\n{Colors.ERROR}{error_symbol} Some services failed to start{Colors.RESET}")
            print(f"   Successful: {', '.join(alive_services)}")
            print(f"   Failed: {', '.join(dead_services + failed_services)}")
            print(f"   Check logs in {logs_dir} for details")
            return False
        
        # All services started successfully - report error/warning counts
        success_symbol = "OK" if platform.system() == "Windows" else "✓"
        print(f"\n{Colors.BOLD}{success_symbol} All services started successfully!{Colors.RESET}\n")
        
        # Report error and warning counts for transparency
        total_errors = sum(manager.error_count for manager in self.services.values())
        total_warnings = sum(manager.warning_count for manager in self.services.values())
        if total_errors > 0 or total_warnings > 0:
            print(f"{Colors.YELLOW}Startup summary: {total_errors} errors, {total_warnings} warnings detected{Colors.RESET}")
            for name, manager in self.services.items():
                if manager.error_count > 0 or manager.warning_count > 0:
                    print(f"  {name}: {manager.error_count} errors, {manager.warning_count} warnings")
            print()
        
        # Display comprehensive startup summary
        print(f"{Colors.BOLD}Full Stack Components:{Colors.RESET}")
        print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} {Colors.BACKEND}Backend API{Colors.RESET}: http://localhost:8000")
        # Show paper trading mode status in agent description
        if self.paper_validator:
            paper_status = "Paper Trading Mode" if self.paper_validator.is_paper_mode else "LIVE TRADING MODE"
        else:
            paper_status = "Running"
        print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} {Colors.AGENT}Agent Service{Colors.RESET}: Running ({paper_status})")
        print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} {Colors.AGENT}Feature Server API{Colors.RESET}: http://localhost:8001")
        print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} {Colors.FRONTEND}Frontend{Colors.RESET}: http://localhost:3000")
        
        # Check database and Redis status
        database_url = os.environ.get("DATABASE_URL", "")
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        
        if database_url and check_postgres_running(database_url):
            host, port, database = parse_database_url(database_url)
            print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} Database: Connected at {host}:{port}")
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.RESET} Database: Status unknown")
        
        if check_redis_running(redis_url):
            host, port = parse_redis_url(redis_url)
            print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} Redis: Connected at {host}:{port}")
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.RESET} Redis: Status unknown")
        
        print(f"\nLogs are in the logs/ directory")
        print(f"API Documentation: http://localhost:8000/docs\n")
        
        # Run health checks after services start
        self._run_health_checks()
        
        # Initialize monitoring components
        self._initialize_monitoring()
        
        print(f"\nPress Ctrl+C to stop all services\n")
        
        return True
    
    def _initialize_monitoring(self):
        """Initialize monitoring components."""
        # Use existing paper validator if available, otherwise create new one
        if self.paper_validator is None:
            self.paper_validator = PaperTradingValidator(self.project_root)
        
        # Initialize WebSocket monitor
        enable_dashboard = os.environ.get("ENABLE_MONITORING_DASHBOARD", "true").lower() in ("true", "1", "yes")
        refresh_interval = float(os.environ.get("MONITORING_REFRESH_INTERVAL", "2.0"))
        clear_screen = os.environ.get("CLEAR_SCREEN_DASHBOARD", "false").lower() in ("true", "1", "yes")
        
        # Configure freshness thresholds
        thresholds = {
            "agent_state": int(os.environ.get("FRESHNESS_THRESHOLD_AGENT_STATE", "60")),
            "market_tick": int(os.environ.get("FRESHNESS_THRESHOLD_MARKET_TICK", "10")),
            "other": int(os.environ.get("FRESHNESS_THRESHOLD_OTHER", "30")),
        }
        
        if WEBSOCKETS_AVAILABLE:
            # Wait a bit for backend to be ready
            time.sleep(3)
            
            # Start WebSocket monitor
            self.ws_monitor = WebSocketMonitor("ws://localhost:8000/ws", thresholds)
            self.ws_monitor.start()
            print(f"{Colors.BOLD}[Monitoring] Starting WebSocket monitor...{Colors.RESET}")
            time.sleep(1)  # Give it time to connect
            if self.ws_monitor.connected:
                print(f"{Colors.GREEN}[Monitoring] WebSocket connected successfully{Colors.RESET}")
            else:
                print(f"{Colors.YELLOW}[Monitoring] WebSocket connection pending...{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}[Monitoring] WebSocket monitoring disabled (websockets library not available){Colors.RESET}")
        
        # Initialize dashboard
        if enable_dashboard:
            self.dashboard = MonitoringDashboard(
                self.services, 
                self.paper_validator, 
                self.ws_monitor,
                refresh_interval=refresh_interval,
                clear_screen=clear_screen
            )
            self.dashboard.start()
            print(f"{Colors.BOLD}[Monitoring] Dashboard enabled (refresh: {refresh_interval}s){Colors.RESET}")
        
        # Initialize validation reporter
        self.validation_reporter = ValidationReporter(self.project_root)
    
    def _run_health_checks(self):
        """Run comprehensive health checks for all services after startup."""
        print(f"\n{Colors.BOLD}Running health checks...{Colors.RESET}")
        
        # Wait a bit more for services to fully initialize
        time.sleep(2)
        
        # Use dynamic frontend port if stored, otherwise default to 3000
        frontend_port = getattr(self, 'frontend_port', 3000)
        services_status = {
            "Backend": {"url": "http://localhost:8000/api/v1/health", "status": "unknown"},
            "Feature Server": {"url": "http://localhost:8001/health", "status": "unknown"},
            "Frontend": {"url": f"http://localhost:{frontend_port}", "status": "unknown"},
        }
        
        # Check Backend
        if self._check_http_endpoint(services_status["Backend"]["url"], expected_status=200):
            services_status["Backend"]["status"] = "healthy"
        else:
            services_status["Backend"]["status"] = "unhealthy"
        
        # Check Feature Server (runs inside Agent)
        if self._check_http_endpoint(services_status["Feature Server"]["url"], expected_status=200, timeout=5):
            services_status["Feature Server"]["status"] = "healthy"
        else:
            services_status["Feature Server"]["status"] = "unhealthy"
        
        # Check Frontend
        if self._check_http_endpoint(services_status["Frontend"]["url"], expected_status=200, timeout=5):
            services_status["Frontend"]["status"] = "healthy"
        else:
            services_status["Frontend"]["status"] = "unhealthy"
        
        # Display results
        print()
        success_symbol = "OK" if platform.system() == "Windows" else "✓"
        error_symbol = "X" if platform.system() == "Windows" else "✗"
        
        for service_name, info in services_status.items():
            if info["status"] == "healthy":
                print(f"{Colors.GREEN}{success_symbol}{Colors.RESET} {service_name}: {info['status'].upper()}")
            else:
                print(f"{Colors.ERROR}{error_symbol}{Colors.RESET} {service_name}: {info['status'].upper()} - {info['url']}")
        
        # Also try external health check script if available
        health_check_script = self.project_root / "tools" / "commands" / "health_check.py"
        if health_check_script.exists():
            try:
                result = subprocess.run(
                    [sys.executable, str(health_check_script), "--no-wait", "--max-wait", "15"],
                    cwd=str(self.project_root),
                    timeout=20,
                    capture_output=False,
                )
                # Health check failures should be reported but don't prevent startup
                # (inline checks above are primary validation)
                if result.returncode != 0:
                    print(
                        f"{Colors.YELLOW}[WARN] Additional health checks reported issues. "
                        f"Check logs above.{Colors.RESET}"
                    )
            except subprocess.TimeoutExpired:
                print(f"{Colors.YELLOW}[WARN] Health check script timed out after 20 seconds{Colors.RESET}")
            except Exception as e:
                # Log health check script errors instead of silently ignoring
                print(f"{Colors.YELLOW}[WARN] Health check script error: {e}{Colors.RESET}", file=sys.stderr)
    
    def _check_http_endpoint(self, url: str, expected_status: int = 200, timeout: float = 3.0) -> bool:
        """Check if an HTTP endpoint is responding.

        Args:
            url: URL to check
            expected_status: Expected HTTP status code
            timeout: Request timeout in seconds

        Returns:
            True if endpoint responds with expected status, False otherwise
        """
        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "JackSparrow-Startup-HealthCheck/1.0")

            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status == expected_status
        except urllib.error.HTTPError as e:
            # HTTP error but service is responding
            return e.code == expected_status
        except (urllib.error.URLError, socket.timeout, Exception):
            return False

    def _check_websocket_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        """Check if a WebSocket endpoint is accessible.

        Args:
            url: WebSocket URL to check (ws:// or wss://)
            timeout: Connection timeout in seconds

        Returns:
            True if WebSocket endpoint accepts connections, False otherwise
        """
        if not WEBSOCKETS_AVAILABLE:
            # WebSocket library not available, skip check
            return False

        try:
            import asyncio
            from urllib.parse import urlparse

            # Parse the URL to extract host and port
            parsed = urlparse(url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == 'wss' else 80)

            # Use asyncio to test WebSocket connection
            async def test_connection():
                try:
                    # Create a simple connection test
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port),
                        timeout=timeout
                    )
                    writer.close()
                    await writer.wait_closed()
                    return True
                except Exception:
                    return False

            # Run the async test
            return asyncio.run(test_connection())

        except Exception:
            return False
    
    def wait_for_services_ready(self, timeout: float = 60.0, retry_interval: float = 2.0) -> Dict[str, bool]:
        """Wait for all services to be healthy and ready.
        
        Args:
            timeout: Maximum time to wait in seconds
            retry_interval: Time between health check retries in seconds
            
        Returns:
            Dictionary mapping service name to health status (True if healthy)
        """
        print(f"\n{Colors.BOLD}Waiting for services to be ready...{Colors.RESET}")
        
        start_time = time.time()
        services_status: Dict[str, bool] = {}
        services_checked: Dict[str, bool] = {}  # Track which services have been checked and logged
        max_retries = int(timeout / retry_interval)
        
        # Service endpoints to check
        # Use dynamic frontend port if stored, otherwise default to 3000
        frontend_port = getattr(self, 'frontend_port', 3000)
        endpoints = {
            "Backend": "http://localhost:8000/api/v1/health",
            "Feature Server": "http://localhost:8001/health",
            "Frontend": f"http://localhost:{frontend_port}"
        }
        
        # Database and Redis URLs
        database_url = os.environ.get("DATABASE_URL", "")
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        
        status_symbol = "OK" if platform.system() == "Windows" else "✓"
        error_symbol = "X" if platform.system() == "Windows" else "✗"
        
        retry_count = 0
        while retry_count < max_retries:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                break
            
            all_ready = True
            
            # Check HTTP endpoints
            for service_name, url in endpoints.items():
                is_healthy = self._check_http_endpoint(url, timeout=5.0)
                services_status[service_name] = is_healthy
                if is_healthy and not services_checked.get(service_name, False):
                    print(f"  {Colors.GREEN}{status_symbol}{Colors.RESET} {service_name}: Ready")
                    services_checked[service_name] = True
                elif not is_healthy:
                    all_ready = False
            
            # Check database
            if database_url:
                db_ready = check_postgres_running(database_url)
                services_status["Database"] = db_ready
                if db_ready and not services_checked.get("Database", False):
                    print(f"  {Colors.GREEN}{status_symbol}{Colors.RESET} Database: Ready")
                    services_checked["Database"] = True
                elif not db_ready:
                    all_ready = False
            
            # Check Redis
            redis_ready = check_redis_running(redis_url)
            services_status["Redis"] = redis_ready
            if redis_ready and not services_checked.get("Redis", False):
                print(f"  {Colors.GREEN}{status_symbol}{Colors.RESET} Redis: Ready")
                services_checked["Redis"] = True
            elif not redis_ready:
                all_ready = False
            
            # Check WebSocket (optional but nice to have)
            # Use proper WebSocket health check instead of HTTP check
            ws_ready = self._check_websocket_endpoint("ws://localhost:8000/ws", timeout=2.0)
            services_status["WebSocket"] = ws_ready
            if ws_ready and not services_checked.get("WebSocket", False):
                print(f"  {Colors.GREEN}{status_symbol}{Colors.RESET} WebSocket: Ready")
                services_checked["WebSocket"] = True
            elif not ws_ready:
                # WebSocket is optional, don't fail if it's not ready
                # Only log once to avoid spam
                if not services_checked.get("WebSocket", False) and retry_count >= max_retries - 1:
                    # Only show warning on final attempt
                    pass
            
            if all_ready and all(services_status.get(k, False) for k in endpoints.keys() if k in services_status):
                if database_url:
                    all_ready = all_ready and services_status.get("Database", False)
                all_ready = all_ready and services_status.get("Redis", False)
                
                if all_ready:
                    print(f"\n{Colors.BOLD}{Colors.GREEN}All services are ready!{Colors.RESET}\n")
                    return services_status
            
            retry_count += 1
            if retry_count < max_retries:
                time.sleep(retry_interval)
        
        # Timeout reached - report what's not ready
        print(f"\n{Colors.YELLOW}Timeout waiting for services (after {timeout}s){Colors.RESET}")
        for service_name, is_ready in services_status.items():
            if not is_ready:
                print(f"  {Colors.ERROR}{error_symbol}{Colors.RESET} {service_name}: Not ready")
        
        return services_status
    
    def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        try:
            while not self.shutdown_event.is_set():
                # Check if any service died unexpectedly
                error_symbol = "X" if platform.system() == "Windows" else "✗"
                for name, manager in self.services.items():
                    if manager.running and not manager.is_alive():
                        print(f"\n{Colors.ERROR}{error_symbol} {name} process died unexpectedly{Colors.RESET}")
                        # Try to get error information
                        if manager.recent_errors:
                            print(f"   Recent errors: {', '.join(manager.recent_errors[:3])}")
                        # Check log file for last entries
                        log_file = manager.config.log_file
                        if log_file and log_file.exists():
                            try:
                                with open(log_file, 'r', encoding='utf-8') as f:
                                    lines = f.readlines()
                                    if lines:
                                        print(f"   Last log entries:")
                                        for line in lines[-3:]:
                                            print(f"     {line.rstrip()}")
                            except Exception:
                                pass
                        self.shutdown_event.set()
                        break
                
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown_event.set()
        
        self.stop_all()
    
    def stop_all(self):
        """Stop all services."""
        # Stop monitoring components
        if self.dashboard:
            self.dashboard.stop()
        
        if self.ws_monitor:
            self.ws_monitor.stop()
        
        # Generate validation report
        if self.validation_reporter and self.paper_validator:
            enable_report = os.environ.get("ENABLE_VALIDATION_REPORT", "true").lower() in ("true", "1", "yes")
            if enable_report:
                print(f"\n{Colors.BOLD}[Monitoring] Generating validation report...{Colors.RESET}")
                report = self.validation_reporter.generate_report(
                    self.services,
                    self.paper_validator,
                    self.ws_monitor
                )
                self.validation_reporter.print_summary(report)
                report_path = self.validation_reporter.save_json(report)
                print(f"Report saved to: {report_path}\n")
        
        print(f"\n{Colors.BOLD}Stopping all services...{Colors.RESET}")
        for manager in self.services.values():
            manager.stop()
        print(f"{Colors.BOLD}All services stopped.{Colors.RESET}")


def get_python_executable(venv_path: Path) -> str:
    """Get Python executable path for virtual environment."""
    if platform.system() == "Windows":
        return str(venv_path / "Scripts" / "python.exe")
    else:
        return str(venv_path / "bin" / "python")


def get_npm_executable() -> str:
    """Get npm executable path, handling Windows npm.cmd resolution."""
    if platform.system() == "Windows":
        for candidate in ("npm.cmd", "npm.exe", "npm"):
            path = shutil.which(candidate)
            if path:
                return path
        raise FileNotFoundError(
            "npm executable not found. Install Node.js 18+ and ensure npm is on PATH."
        )
    path = shutil.which("npm")
    if not path:
        raise FileNotFoundError(
            "npm executable not found. Install Node.js 18+ and ensure npm is on PATH."
        )
    return path


def _is_signature_stale(stamp_path: Path, signature: str) -> bool:
    """Check whether dependency signature differs from recorded stamp."""
    if not signature:
        return False
    if not stamp_path.exists():
        return True
    try:
        return stamp_path.read_text(encoding="utf-8").strip() != signature
    except OSError:
        return True


def _install_python_dependencies(
    component_name: str, python_exec: str, requirements_path: Path
) -> None:
    """Install Python requirements when the requirements file changes."""
    if not requirements_path.exists():
        return
    
    signature = str(requirements_path.stat().st_mtime_ns)
    stamp_path = requirements_path.parent / ".deps_stamp"
    
    if not _is_signature_stale(stamp_path, signature):
        print(f"  {component_name.capitalize()} dependencies up to date")
        return
    
    print(f"  Installing {component_name} dependencies...")
    subprocess.run(
        [python_exec, "-m", "pip", "install", "-r", str(requirements_path)],
        cwd=str(requirements_path.parent),
        check=True,
    )
    stamp_path.write_text(signature, encoding="utf-8")


def _install_frontend_dependencies(frontend_dir: Path, npm_cmd: str) -> None:
    """Install frontend dependencies when package metadata changes."""
    lock_file = frontend_dir / "package-lock.json"
    source = lock_file if lock_file.exists() else frontend_dir / "package.json"
    if not source.exists():
        return
    
    signature = str(source.stat().st_mtime_ns)
    stamp_path = frontend_dir / ".deps_stamp"
    
    if not _is_signature_stale(stamp_path, signature):
        print("  Frontend dependencies up to date")
        return
    
    print("  Installing frontend dependencies...")
    subprocess.run(
        [npm_cmd, "install"],
        cwd=str(frontend_dir),
        check=True,
    )
    stamp_path.write_text(signature, encoding="utf-8")


def setup_services(project_root: Path, npm_cmd: str) -> ParallelProcessManager:
    """Setup service configurations."""
    manager = ParallelProcessManager(project_root)
    logs_dir = project_root / "logs"
    
    # Backend service
    backend_venv = project_root / "backend" / "venv"
    backend_python = get_python_executable(backend_venv)
    
    backend_config = ServiceConfig(
        name="Backend",
        color=Colors.BACKEND,
        command=[
            backend_python,
            "-m", "uvicorn",
            "backend.api.main:app",
            "--host", "0.0.0.0",
            "--port", "8000"
        ],
        cwd=project_root,
        log_file=logs_dir / "backend.log",
        pid_file=logs_dir / "backend.pid",
        check_delay=2.0
    )
    manager.add_service(backend_config)
    
    # Agent service
    agent_venv = project_root / "agent" / "venv"
    agent_python = get_python_executable(agent_venv)
    
    agent_config = ServiceConfig(
        name="Agent",
        color=Colors.AGENT,
        command=[
            agent_python,
            "-m", "agent.core.intelligent_agent"
        ],
        cwd=project_root,
        # Capture agent logs for visibility in startup script
        # Agent also writes structured logs, but we capture stdout/stderr here
        log_file=logs_dir / "agent_startup.log",
        pid_file=logs_dir / "agent.pid",
        check_delay=2.0
    )
    manager.add_service(agent_config)
    
    # Frontend service - check for port conflicts
    frontend_port = 3000
    if check_port_accessible("localhost", frontend_port):
        # Port 3000 is in use, try to find an alternative
        for alt_port in range(3001, 3010):
            if not check_port_accessible("localhost", alt_port):
                frontend_port = alt_port
                print(f"{Colors.YELLOW}⚠ Port 3000 is in use, using port {frontend_port} for frontend{Colors.RESET}")
                break
        else:
            # If no free port found, warn but continue (Next.js will handle the error)
            print(f"{Colors.YELLOW}⚠ Port 3000 is in use and no alternative port found, frontend may fail to start{Colors.RESET}")
    
    # Store frontend port in manager for health checks
    manager.frontend_port = frontend_port
    
    # Frontend service
    # Use npm run dev with -- to pass arguments, overriding package.json script
    frontend_config = ServiceConfig(
        name="Frontend",
        color=Colors.FRONTEND,
        command=[npm_cmd, "run", "dev", "--", "-p", str(frontend_port)],  # Use dynamic port
        cwd=project_root / "frontend",
        log_file=logs_dir / "frontend.log",
        pid_file=logs_dir / "frontend.pid",
        check_delay=3.0,  # Frontend takes longer to start
    )
    manager.add_service(frontend_config)
    
    return manager


def ensure_dependencies(project_root: Path, npm_cmd: str):
    """Ensure virtual environments and dependencies are set up."""
    print(f"{Colors.BOLD}Checking dependencies...{Colors.RESET}")
    
    # Check backend venv
    backend_venv = project_root / "backend" / "venv"
    if not backend_venv.exists():
        print(f"  Creating backend virtual environment...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(backend_venv)],
            cwd=str(project_root / "backend"),
            check=True
        )
    
    # Check agent venv
    agent_venv = project_root / "agent" / "venv"
    if not agent_venv.exists():
        print(f"  Creating agent virtual environment...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(agent_venv)],
            cwd=str(project_root / "agent"),
            check=True
        )
    
    # Install backend dependencies (only when requirements change)
    backend_python = get_python_executable(backend_venv)
    backend_reqs = project_root / "backend" / "requirements.txt"
    _install_python_dependencies("backend", backend_python, backend_reqs)
    
    # Install agent dependencies (quiet mode)
    agent_python = get_python_executable(agent_venv)
    agent_reqs = project_root / "agent" / "requirements.txt"
    _install_python_dependencies("agent", agent_python, agent_reqs)
    
    # Check frontend node_modules
    frontend_dir = project_root / "frontend"
    _install_frontend_dependencies(frontend_dir, npm_cmd)
    
    print()  # Empty line after dependency check


def load_root_env(project_root: Path):
    """Load environment variables from project-level .env, if present."""
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    print(f"{Colors.BOLD}Loading environment from .env{Colors.RESET}")
    try:
        with env_path.open("r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # Do not override explicitly set environment variables
                if key and key not in os.environ:
                    os.environ[key] = value

                # Backward compatible aliases
                if key == "DELTA_API_KEY":
                    os.environ.setdefault("DELTA_EXCHANGE_API_KEY", value)
                elif key == "DELTA_API_SECRET":
                    os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", value)
                elif key == "DELTA_API_URL":
                    os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", value)
    except Exception as exc:
        print(f"{Colors.ERROR}Failed to load .env: {exc}{Colors.RESET}")
        print(f"{Colors.ERROR}Startup cannot continue without valid .env file.{Colors.RESET}")
        # Don't exit here - let validation scripts handle it, but make it clear this is an error


def parse_database_url(url: str) -> Tuple[str, int, str]:
    """Parse PostgreSQL DATABASE_URL.
    
    Handles formats:
    - postgresql://user:pass@host:port/dbname
    - postgresql+asyncpg://user:pass@host:port/dbname
    
    Args:
        url: Database connection URL
        
    Returns:
        Tuple of (host, port, database_name)
    """
    if not url:
        return ("localhost", 5432, "")
    
    # Remove scheme prefix if present (postgresql+asyncpg:// -> postgresql://)
    if "+" in url and "://" in url:
        scheme_part, rest = url.split("://", 1)
        url = f"postgresql://{rest}"
    
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        database = parsed.path.lstrip("/") if parsed.path else ""
        return (host, port, database)
    except Exception:
        # Fallback to defaults if parsing fails
        return ("localhost", 5432, "")


def parse_redis_url(url: str) -> Tuple[str, int]:
    """Parse Redis REDIS_URL.
    
    Handles formats:
    - redis://host:port
    - redis://localhost:6379
    
    Args:
        url: Redis connection URL
        
    Returns:
        Tuple of (host, port)
    """
    if not url:
        return ("localhost", 6379)
    
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        return (host, port)
    except Exception:
        # Fallback to defaults if parsing fails
        return ("localhost", 6379)


def check_port_accessible(host: str, port: int, timeout: float = 2.0) -> bool:
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
    except Exception:
        return False


def check_postgres_running(database_url: str) -> bool:
    """Check if PostgreSQL is accessible.
    
    Args:
        database_url: PostgreSQL connection URL
        
    Returns:
        True if PostgreSQL is accessible, False otherwise
    """
    host, port, _ = parse_database_url(database_url)
    return check_port_accessible(host, port)


def check_redis_running(redis_url: str) -> bool:
    """Check if Redis is accessible.
    
    Args:
        redis_url: Redis connection URL
        
    Returns:
        True if Redis is accessible, False otherwise
    """
    host, port = parse_redis_url(redis_url)
    return check_port_accessible(host, port)


def print_prerequisite_error(issues: List[str]):
    """Print formatted prerequisite error messages with platform-specific instructions.
    
    Args:
        issues: List of prerequisite issues found
    """
    # Use ASCII-safe characters for Windows compatibility
    error_symbol = "X" if platform.system() == "Windows" else "✗"
    print(f"\n{Colors.ERROR}{error_symbol} Prerequisites Check Failed{Colors.RESET}\n")
    print("The following required services are not running:")
    bullet = "-" if platform.system() == "Windows" else "•"
    for issue in issues:
        print(f"  {bullet} {issue}")
    
    print(f"\n{Colors.BOLD}To fix this:{Colors.RESET}\n")
    
    # Platform-specific instructions
    system = platform.system()
    bullet = "-" if system == "Windows" else "•"
    
    if system == "Windows":
        print("1. Start PostgreSQL:")
        print("   PowerShell (as Administrator):")
        print("   Get-Service postgresql* | Start-Service")
        print("   # Or if you know the service name:")
        print("   net start postgresql-x64-15")
        print("\n2. Start Redis:")
        print("   PowerShell (as Administrator):")
        print("   Get-Service redis* | Start-Service")
        print("   # Or if installed as service:")
        print("   net start redis")
        print("\n3. Verify services are running:")
        print("   Get-Service postgresql*, redis*")
    elif system == "Darwin":  # macOS
        print("1. Start PostgreSQL:")
        print("   brew services start postgresql@15")
        print("\n2. Start Redis:")
        print("   brew services start redis")
        print("\n3. Verify services are running:")
        print("   brew services list")
    else:  # Linux
        print("1. Start PostgreSQL:")
        print("   sudo systemctl start postgresql")
        print("\n2. Start Redis:")
        print("   sudo systemctl start redis")
        print("\n3. Verify services are running:")
        print("   sudo systemctl status postgresql redis")
    
    print(f"\n{Colors.BOLD}For detailed setup instructions, see docs/10-deployment.md{Colors.RESET}\n")


def attempt_start_redis(project_root: Path) -> bool:
    """Attempt to start Redis if it's not already running.
    
    Args:
        project_root: Project root directory
        
    Returns:
        True if Redis is now accessible, False otherwise
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    host, port = parse_redis_url(redis_url)
    
    # Check if Redis is already accessible
    if check_redis_running(redis_url):
        return True
    
    print(f"{Colors.BOLD}Redis not accessible at {host}:{port}. Attempting to start...{Colors.RESET}")
    
    if platform.system() == "Windows":
        # Try bundled Redis server
        redis_exe = project_root / "redis-tmp" / "redis-server.exe"
        redis_config = project_root / "redis-tmp" / "redis.windows.conf"
        
        if redis_exe.exists():
            try:
                # Start Redis in background
                subprocess.Popen(
                    [str(redis_exe), str(redis_config)],
                    cwd=str(redis_exe.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                # Wait a moment for Redis to start
                time.sleep(2)
                if check_redis_running(redis_url):
                    check_mark = get_safe_symbol("✓", "+")
                    print(f"{Colors.GREEN}{check_mark} Redis started successfully{Colors.RESET}")
                    return True
            except Exception as e:
                warning = get_safe_symbol("⚠", "!")
                print(f"{Colors.YELLOW}{warning} Failed to start bundled Redis: {e}{Colors.RESET}")
        
        # Try Windows service
        try:
            redis_services = subprocess.run(
                ["powershell", "-Command", "Get-Service -Name 'redis*' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Name"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if redis_services.returncode == 0 and redis_services.stdout.strip():
                service_name = redis_services.stdout.strip()
                subprocess.run(
                    ["powershell", "-Command", f"Start-Service -Name '{service_name}'"],
                    capture_output=True,
                    timeout=10
                )
                time.sleep(2)
                if check_redis_running(redis_url):
                    check_mark = get_safe_symbol("✓", "+")
                    print(f"{Colors.GREEN}{check_mark} Redis service started: {service_name}{Colors.RESET}")
                    return True
        except Exception as e:
            # Log Redis service start errors instead of silently ignoring
            print(f"{Colors.YELLOW}[Redis] Service start attempt failed: {e}{Colors.RESET}", file=sys.stderr)
    else:
        # Unix/Linux/macOS: Try redis-server command
        try:
            redis_cmd = shutil.which("redis-server")
            if redis_cmd:
                # Start Redis in daemon mode
                subprocess.Popen(
                    [redis_cmd, "--daemonize", "yes"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                time.sleep(2)
                if check_redis_running(redis_url):
                    check_mark = get_safe_symbol("✓", "+")
                    print(f"{Colors.GREEN}{check_mark} Redis started successfully{Colors.RESET}")
                    return True
        except Exception as e:
            warning = get_safe_symbol("⚠", "!")
            print(f"{Colors.YELLOW}{warning} Failed to start Redis: {e}{Colors.RESET}")
    
    # Redis still not accessible after attempts
    return False


def verify_database_schema(database_url: str) -> Tuple[bool, bool]:
    """Verify database schema exists and optionally initialize if missing.
    
    Args:
        database_url: PostgreSQL connection URL
        
    Returns:
        Tuple of (schema_exists: bool, auto_initialized: bool)
    """
    if not SQLALCHEMY_AVAILABLE:
        # Skip schema check if SQLAlchemy not available
        return True, False
    
    required_tables = [
        "trades",
        "positions",
        "decisions",
        "performance_metrics",
        "model_performance",
    ]
    
    try:
        # Normalize database URL for SQLAlchemy
        normalized_url = database_url
        if "+" in database_url and "://" in database_url:
            scheme_part, rest = database_url.split("://", 1)
            normalized_url = f"postgresql://{rest}"
        elif not database_url.startswith(("postgresql://", "postgres://")):
            # Skip if URL format is invalid
            return True, False
        
        engine = create_engine(normalized_url, connect_args={"connect_timeout": 5})
        inspector = inspect(engine)
        
        existing_tables = inspector.get_table_names()
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            # Schema is missing - check if auto-initialization is enabled
            auto_init = os.environ.get("AUTO_INIT_DB", "").lower() in ("1", "true", "yes")
            auto_create_schema = os.environ.get("AUTO_CREATE_DB_SCHEMA", "").lower() in ("1", "true", "yes")
            
            # Use AUTO_CREATE_DB_SCHEMA if set, otherwise fall back to AUTO_INIT_DB
            should_auto_init = auto_create_schema or auto_init
            
            if should_auto_init:
                # Attempt to auto-initialize database
                setup_script = Path(__file__).parent.parent.parent / "scripts" / "setup_db.py"
                if setup_script.exists():
                    print(f"{Colors.YELLOW}Database schema missing. Auto-initializing...{Colors.RESET}")
                    try:
                        result = subprocess.run(
                            [sys.executable, str(setup_script)],
                            cwd=str(setup_script.parent.parent),
                            capture_output=True,
                            text=True,
                            timeout=60
                        )
                        if result.returncode == 0:
                            success_symbol = "OK" if platform.system() == "Windows" else "✓"
                            print(f"{Colors.GREEN}{success_symbol} Database schema initialized successfully{Colors.RESET}")
                            return True, True
                        else:
                            error_msg = result.stderr or result.stdout
                            print(f"{Colors.ERROR}Failed to auto-initialize database: {error_msg[:200]}{Colors.RESET}")
                            return False, False
                    except Exception as e:
                        print(f"{Colors.ERROR}Error during auto-initialization: {e}{Colors.RESET}")
                        return False, False
                else:
                    print(f"{Colors.ERROR}Database setup script not found: {setup_script}{Colors.RESET}")
                    return False, False
            else:
                # Schema missing but auto-init not enabled - this should prevent startup
                error_symbol = "X" if platform.system() == "Windows" else "✗"
                print(f"{Colors.ERROR}{error_symbol} Database schema missing: {', '.join(missing_tables)}{Colors.RESET}")
                print(f"  Run 'python scripts/setup_db.py' to initialize schema")
                print(f"  Or set AUTO_CREATE_DB_SCHEMA=1 or AUTO_INIT_DB=1 to auto-initialize on startup")
                print(f"{Colors.ERROR}Startup cannot continue without database schema.{Colors.RESET}")
                return False, False
        else:
            # Schema exists
            success_symbol = "OK" if platform.system() == "Windows" else "✓"
            print(f"{Colors.GREEN}{success_symbol} Database schema verified (all tables exist){Colors.RESET}")
            return True, False
            
    except Exception as e:
        # Don't fail startup if schema check fails, just warn
        warning_symbol = "!" if platform.system() == "Windows" else "⚠"
        print(f"{Colors.YELLOW}{warning_symbol} Could not verify database schema: {str(e)[:100]}{Colors.RESET}")
        print(f"  Ensure database is initialized with 'python scripts/setup_db.py'")
        # Return True to allow startup to continue
        return True, False


def check_prerequisites() -> bool:
    """Check if required services (PostgreSQL, Redis) are running and schema exists.
    
    Reads DATABASE_URL and REDIS_URL from environment variables
    (loaded by load_root_env) and verifies services are accessible.
    
    Returns:
        True if all prerequisites met, False otherwise.
    """
    issues = []
    
    # Get URLs from environment
    database_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    
    if not database_url:
        issues.append("DATABASE_URL environment variable not set")
    elif not check_postgres_running(database_url):
        host, port, database = parse_database_url(database_url)
        if database:
            issues.append(f"PostgreSQL is not accessible at {host}:{port} (database: {database})")
        else:
            issues.append(f"PostgreSQL is not accessible at {host}:{port}")
    else:
        # Database is accessible, verify schema
        schema_exists, auto_init = verify_database_schema(database_url)
        if not schema_exists:
            # Schema check failed - this should prevent startup
            issues.append("Database schema is missing or invalid. Run 'python scripts/setup_db.py' to initialize.")
    
    if not check_redis_running(redis_url):
        host, port = parse_redis_url(redis_url)
        issues.append(f"Redis is not accessible at {host}:{port}")
    
    if issues:
        print_prerequisite_error(issues)
        return False
    
    success_symbol = "OK" if platform.system() == "Windows" else "✓"
    print(f"{Colors.BOLD}{success_symbol} Prerequisites check passed{Colors.RESET}\n")
    return True


def run_validation_script(script_path: Path, script_name: str, project_root: Path) -> bool:
    """Run a validation script and return success status.
    
    Args:
        script_path: Path to validation script
        script_name: Name of script for error messages
        
    Returns:
        True if validation passed, False otherwise
    """
    # Always print what script is being run
    print(f"{Colors.BOLD}Running {script_name}...{Colors.RESET}")
    print(f"  Script path: {script_path}")
    sys.stdout.flush()
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        # Always print output, even if empty - this ensures visibility
        if result.stdout:
            print(result.stdout)
        else:
            print(f"  {script_name} produced no output")
        
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        # Flush after printing
        sys.stdout.flush()
        sys.stderr.flush()
        
        # Show result clearly
        if result.returncode != 0:
            error_symbol = "X" if platform.system() == "Windows" else "✗"
            print(f"{Colors.ERROR}{error_symbol} {script_name} failed with exit code {result.returncode}{Colors.RESET}")
            sys.stdout.flush()
        
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"{Colors.ERROR}Timeout running {script_name} (exceeded 30 seconds){Colors.RESET}")
        sys.stdout.flush()
        return False
    except Exception as e:
        print(f"{Colors.ERROR}Error running {script_name}: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        return False


def main():
    """Main entry point."""
    # Wrap entire execution in try/except for comprehensive error handling
    try:
        # Get project root (parent of tools/commands directory)
        script_path = Path(__file__).resolve()
        project_root = script_path.parent.parent.parent
        
        # Change to project root
        os.chdir(str(project_root))
        
        # Startup banner - always printed
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}JackSparrow Trading Agent - Startup Sequence{Colors.RESET}")
        print(f"{Colors.BOLD}Process ID: {os.getpid()}{Colors.RESET}")
        print(f"{Colors.BOLD}Project root: {project_root}{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print()
        sys.stdout.flush()
        
        # Resolve npm command early (raises if missing)
        try:
            npm_cmd = get_npm_executable()
        except FileNotFoundError as exc:
            print(f"{Colors.ERROR}{exc}{Colors.RESET}")
            print(f"\n{Colors.BOLD}Please install Node.js 18+ and ensure npm is in your PATH{Colors.RESET}")
            sys.stdout.flush()
            sys.stderr.flush()
            sys.exit(1)

        print(f"{Colors.BOLD}Step 1/4: Loading environment configuration...{Colors.RESET}")
        sys.stdout.flush()
        # Load root .env so child processes inherit environment variables
        load_root_env(project_root)
        print()
        sys.stdout.flush()
        
        # Validate paper trading mode before starting services
        print(f"{Colors.BOLD}[Paper Trading] Validating configuration...{Colors.RESET}")
        sys.stdout.flush()
        paper_validator = PaperTradingValidator(project_root)
        is_valid, status_msg = paper_validator.validate_startup()
        if is_valid:
            success_symbol = "OK" if platform.system() == "Windows" else "✓"
            print(f"{Colors.BOLD}[Paper Trading] {Colors.GREEN}{success_symbol}{Colors.RESET} Mode: {status_msg}{Colors.RESET}")
        else:
            warning_symbol = "!" if platform.system() == "Windows" else "⚠"
            print(f"{Colors.BOLD}[Paper Trading] {Colors.ERROR}{warning_symbol}{Colors.RESET} Mode: {status_msg}{Colors.RESET}")
            print(f"{Colors.ERROR}WARNING: Live trading mode detected! Real trades will be executed!{Colors.RESET}")
        print()
        sys.stdout.flush()

        print(f"{Colors.BOLD}Step 2/4: Checking Redis availability...{Colors.RESET}")
        sys.stdout.flush()
        # Attempt to start Redis if not already running
        attempt_start_redis(project_root)
        print()  # Empty line after Redis attempt
        sys.stdout.flush()

        print(f"{Colors.BOLD}Step 3/4: Running configuration validators...{Colors.RESET}")
        sys.stdout.flush()
        # Validate .env file contents before proceeding
        env_validator_path = project_root / "scripts" / "validate-env.py"
        if env_validator_path.exists():
            print(f"{Colors.BOLD}Validating environment variables...{Colors.RESET}")
            sys.stdout.flush()
            if not run_validation_script(env_validator_path, "validate-env.py", project_root):
                print(
                    f"\n{Colors.ERROR}Environment validation failed. Please fix .env file issues above.{Colors.RESET}"
                )
                print(f"Run manually: python {env_validator_path}")
                sys.stdout.flush()
                sys.stderr.flush()
                sys.exit(1)
            print()  # Empty line after validation
            sys.stdout.flush()
        
        # Validate prerequisites (Python, Node.js, PostgreSQL, Redis)
        prereq_validator_path = project_root / "tools" / "commands" / "validate-prerequisites.py"
        if prereq_validator_path.exists():
            if not run_validation_script(prereq_validator_path, "validate-prerequisites.py", project_root):
                print(f"\n{Colors.ERROR}Prerequisite validation failed. Please fix issues above.{Colors.RESET}")
                print(f"Run manually: python {prereq_validator_path}")
                sys.stdout.flush()
                sys.stderr.flush()
                sys.exit(1)
        else:
            # Fallback to built-in prerequisite check
            print(f"{Colors.BOLD}Checking prerequisites...{Colors.RESET}")
            sys.stdout.flush()
            if not check_prerequisites():
                sys.stdout.flush()
                sys.stderr.flush()
                sys.exit(1)
    
        # Optional model validation (if enabled)
        validate_models_on_startup = os.environ.get("VALIDATE_MODELS_ON_STARTUP", "").lower() in ("1", "true", "yes")
        if validate_models_on_startup:
            print(f"{Colors.BOLD}Validating model files...{Colors.RESET}")
            sys.stdout.flush()
            model_validator_path = project_root / "scripts" / "validate_model_files.py"
            if model_validator_path.exists():
                if not run_validation_script(model_validator_path, "validate_model_files.py", project_root):
                    print(f"\n{Colors.ERROR}Model validation failed. Models may be corrupted.{Colors.RESET}")
                    print(
                        f"{Colors.YELLOW}Warning: Continuing startup despite model validation failure.{Colors.RESET}"
                    )
                    print("   To fix models, run: python scripts/train_models.py")
                    print(
                        "   To disable this check, unset VALIDATE_MODELS_ON_STARTUP environment variable"
                    )
                print()  # Empty line after validation
                sys.stdout.flush()

        print(f"{Colors.BOLD}Step 4/4: Ensuring service dependencies...{Colors.RESET}")
        sys.stdout.flush()
        # Ensure dependencies are set up
        try:
            ensure_dependencies(project_root, npm_cmd)
        except Exception as e:
            print(f"{Colors.ERROR}Error setting up dependencies: {e}{Colors.RESET}")
            print(f"\n{Colors.BOLD}Troubleshooting:{Colors.RESET}")
            print(f"  1. Ensure Python 3.11+ is installed: python --version")
            print(f"  2. Ensure Node.js 18+ is installed: node --version")
            print(f"  3. Check virtual environment creation permissions")
            print(f"  4. See docs/troubleshooting-local-startup.md for more help")
            sys.stdout.flush()
            sys.stderr.flush()
            sys.exit(1)
        
        print(f"{Colors.BOLD}Preparing service manager...{Colors.RESET}")
        sys.stdout.flush()
        # Setup and start services
        try:
            manager = setup_services(project_root, npm_cmd)
            # Store paper validator reference for monitoring
            manager.paper_validator = paper_validator
            
            if not manager.start_all():
                print(f"\n{Colors.ERROR}Failed to start services. Check logs above for details.{Colors.RESET}")
                print(f"\n{Colors.BOLD}Troubleshooting:{Colors.RESET}")
                print(f"  1. Check service logs in logs/ directory")
                print(f"  2. Verify all prerequisites are running (PostgreSQL, Redis)")
                print(f"  3. Ensure ports 8000 and 3000 are available (port 8001 is only needed if you run the optional feature server separately)")
                print(f"  4. Run validation scripts manually:")
                print(f"     - python scripts/validate-env.py")
                print(f"     - python tools/commands/validate-prerequisites.py")
                print(f"  5. See docs/troubleshooting-local-startup.md for more help")
                sys.stdout.flush()
                sys.stderr.flush()
                sys.exit(1)
        except Exception as e:
            print(f"\n{Colors.ERROR}Unexpected error during service startup: {e}{Colors.RESET}")
            import traceback
            traceback.print_exc()
            print(f"\n{Colors.BOLD}Please report this error and include the traceback above.{Colors.RESET}")
            sys.stdout.flush()
            sys.stderr.flush()
            sys.exit(1)
        
        # Wait for shutdown signal
        try:
            manager.wait_for_shutdown()
        except KeyboardInterrupt:
            manager.stop_all()
            sys.stdout.flush()
            sys.stderr.flush()
            sys.exit(0)
    except Exception as e:
        # Catch any unexpected errors at the top level
        print(f"\n{Colors.ERROR}{'='*60}{Colors.RESET}")
        print(f"{Colors.ERROR}CRITICAL ERROR: Unexpected exception in main(){Colors.RESET}")
        print(f"{Colors.ERROR}Error: {e}{Colors.RESET}")
        print(f"{Colors.ERROR}{'='*60}{Colors.RESET}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()

