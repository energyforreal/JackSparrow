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
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

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


class ServiceManager:
    """Manages a single service process."""
    
    def __init__(self, config: ServiceConfig, project_root: Path):
        self.config = config
        self.project_root = project_root
        self.process: Optional[subprocess.Popen] = None
        self.log_thread: Optional[threading.Thread] = None
        self.running = False
        
    def start(self) -> bool:
        """Start the service process."""
        try:
            # Prepare command
            cmd = self.config.command
            cwd = self.config.cwd or self.project_root
            
            # Ensure log directory exists
            if self.config.log_file:
                self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Start process with UTF-8 encoding to handle Windows charmap issues
            self.process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',  # Replace invalid bytes instead of failing
                bufsize=1,
                universal_newlines=True,
            )
            
            # Check if process started successfully
            if self.process.poll() is not None:
                # Process exited immediately - capture error output
                stdout, _ = self.process.communicate(timeout=1)
                error_msg = stdout.strip() if stdout else "Process exited immediately"
                error_symbol = "X" if platform.system() == "Windows" else "✗"
                print(f"{Colors.ERROR}{error_symbol} {self.config.name} failed to start: {error_msg}{Colors.RESET}")
                return False
            
            # Write PID file
            if self.config.pid_file:
                self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config.pid_file, 'w') as f:
                    f.write(str(self.process.pid))
            
            self.running = True
            
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
                            # Log file write error, but continue streaming to console
                            pass
                    
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
                print(f"{Colors.ERROR}Log streaming error for {self.config.name}: {error_msg}{Colors.RESET}")
            except UnicodeEncodeError:
                print(f"[ERROR] Log streaming error for {self.config.name}: {repr(error_msg)}")
        finally:
            if log_file_handle:
                try:
                    log_file_handle.close()
                except Exception:
                    pass
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
                        with open(log_file, 'r') as f:
                            lines = f.readlines()
                            if lines:
                                last_line = lines[-1].strip()
                                if last_line:
                                    print(f"   Last log entry: {last_line[:100]}")
                    except Exception:
                        pass
        
        if dead_services:
            error_symbol = "X" if platform.system() == "Windows" else "✗"
            print(f"\n{Colors.ERROR}{error_symbol} Some services failed to start{Colors.RESET}")
            print(f"   Successful: {', '.join(alive_services)}")
            print(f"   Failed: {', '.join(dead_services + failed_services)}")
            print(f"   Check logs in {logs_dir} for details")
            return False
        
        # All services started successfully
        success_symbol = "OK" if platform.system() == "Windows" else "✓"
        print(f"\n{Colors.BOLD}{success_symbol} All services started successfully!{Colors.RESET}\n")
        
        # Display comprehensive startup summary
        print(f"{Colors.BOLD}Full Stack Components:{Colors.RESET}")
        print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} {Colors.BACKEND}Backend API{Colors.RESET}: http://localhost:8000")
        print(f"  {Colors.GREEN}{success_symbol}{Colors.RESET} {Colors.AGENT}Agent Service{Colors.RESET}: Running (includes Feature Server on port 8001)")
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
        
        print(f"\nPress Ctrl+C to stop all services\n")
        
        return True
    
    def _run_health_checks(self):
        """Run comprehensive health checks for all services after startup."""
        print(f"\n{Colors.BOLD}Running health checks...{Colors.RESET}")
        
        # Wait a bit more for services to fully initialize
        time.sleep(2)
        
        services_status = {
            "Backend": {"url": "http://localhost:8000/api/v1/health", "status": "unknown"},
            "Feature Server": {"url": "http://localhost:8001/health", "status": "unknown"},
            "Frontend": {"url": "http://localhost:3000", "status": "unknown"},
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
                # Don't fail startup if health check fails, just report
                if result.returncode != 0:
                    print(
                        f"{Colors.YELLOW}[WARN] Additional health checks reported issues. "
                        f"Check logs above.{Colors.RESET}"
                    )
            except (subprocess.TimeoutExpired, Exception):
                # Already have inline checks above; ignore secondary health script failures
                pass
    
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
    
    def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        try:
            while not self.shutdown_event.is_set():
                # Check if any service died unexpectedly
                error_symbol = "X" if platform.system() == "Windows" else "✗"
                for name, manager in self.services.items():
                    if manager.running and not manager.is_alive():
                        print(f"\n{Colors.ERROR}{error_symbol} {name} process died unexpectedly{Colors.RESET}")
                        self.shutdown_event.set()
                        break
                
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown_event.set()
        
        self.stop_all()
    
    def stop_all(self):
        """Stop all services."""
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
        # Agent manages its own structured log file; avoid duplicating stream capture here.
        log_file=None,
        pid_file=logs_dir / "agent.pid",
        check_delay=2.0
    )
    manager.add_service(agent_config)
    
    # Frontend service
    frontend_config = ServiceConfig(
        name="Frontend",
        color=Colors.FRONTEND,
        command=[npm_cmd, "run", "dev"],
        cwd=project_root / "frontend",
        log_file=logs_dir / "frontend.log",
        pid_file=logs_dir / "frontend.pid",
        check_delay=3.0  # Frontend takes longer to start
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
        except Exception:
            pass
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
            
            if auto_init:
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
                # Schema missing but auto-init not enabled
                warning_symbol = "!" if platform.system() == "Windows" else "⚠"
                print(f"{Colors.YELLOW}{warning_symbol} Database schema missing: {', '.join(missing_tables)}{Colors.RESET}")
                print(f"  Run 'python scripts/setup_db.py' to initialize schema")
                print(f"  Or set AUTO_INIT_DB=1 to auto-initialize on startup")
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
            # Schema check failed - this is a warning, not a fatal error
            # But we'll allow startup to continue
            pass
    
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
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"{Colors.ERROR}Timeout running {script_name}{Colors.RESET}")
        return False
    except Exception as e:
        print(f"{Colors.ERROR}Error running {script_name}: {e}{Colors.RESET}")
        return False


def main():
    """Main entry point."""
    # Get project root (parent of tools/commands directory)
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent.parent
    
    # Change to project root
    os.chdir(str(project_root))

    print(f"{Colors.BOLD}JackSparrow startup sequence initiated (PID {os.getpid()}){Colors.RESET}")
    print(f"Project root: {project_root}")
    print()
    
    # Resolve npm command early (raises if missing)
    try:
        npm_cmd = get_npm_executable()
    except FileNotFoundError as exc:
        print(f"{Colors.ERROR}{exc}{Colors.RESET}")
        print(f"\n{Colors.BOLD}Please install Node.js 18+ and ensure npm is in your PATH{Colors.RESET}")
        sys.exit(1)

    print(f"{Colors.BOLD}Step 1/4: Loading environment configuration...{Colors.RESET}")
    # Load root .env so child processes inherit environment variables
    load_root_env(project_root)
    print()

    print(f"{Colors.BOLD}Step 2/4: Checking Redis availability...{Colors.RESET}")
    # Attempt to start Redis if not already running
    attempt_start_redis(project_root)
    print()  # Empty line after Redis attempt

    print(f"{Colors.BOLD}Step 3/4: Running configuration validators...{Colors.RESET}")
    # Validate .env file contents before proceeding
    env_validator_path = project_root / "scripts" / "validate-env.py"
    if env_validator_path.exists():
        print(f"{Colors.BOLD}Validating environment variables...{Colors.RESET}")
        if not run_validation_script(env_validator_path, "validate-env.py", project_root):
            print(
                f"\n{Colors.ERROR}Environment validation failed. Please fix .env file issues above.{Colors.RESET}"
            )
            print(f"Run manually: python {env_validator_path}")
            sys.exit(1)
        print()  # Empty line after validation
    
    # Validate prerequisites (Python, Node.js, PostgreSQL, Redis)
    prereq_validator_path = project_root / "tools" / "commands" / "validate-prerequisites.py"
    if prereq_validator_path.exists():
        if not run_validation_script(prereq_validator_path, "validate-prerequisites.py", project_root):
            print(f"\n{Colors.ERROR}Prerequisite validation failed. Please fix issues above.{Colors.RESET}")
            print(f"Run manually: python {prereq_validator_path}")
            sys.exit(1)
    else:
        # Fallback to built-in prerequisite check
        print(f"{Colors.BOLD}Checking prerequisites...{Colors.RESET}")
        if not check_prerequisites():
            sys.exit(1)
    
    # Optional model validation (if enabled)
    validate_models_on_startup = os.environ.get("VALIDATE_MODELS_ON_STARTUP", "").lower() in ("1", "true", "yes")
    if validate_models_on_startup:
        print(f"{Colors.BOLD}Validating model files...{Colors.RESET}")
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

    print(f"{Colors.BOLD}Step 4/4: Ensuring service dependencies...{Colors.RESET}")
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
        sys.exit(1)
    
    print(f"{Colors.BOLD}Preparing service manager...{Colors.RESET}")
    # Setup and start services
    try:
        manager = setup_services(project_root, npm_cmd)
        
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
            sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.ERROR}Unexpected error during service startup: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        print(f"\n{Colors.BOLD}Please report this error and include the traceback above.{Colors.RESET}")
        sys.exit(1)
    
    # Wait for shutdown signal
    try:
        manager.wait_for_shutdown()
    except KeyboardInterrupt:
        manager.stop_all()
        sys.exit(0)


if __name__ == "__main__":
    main()

