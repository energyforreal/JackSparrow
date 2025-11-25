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
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes for service identification."""
    BACKEND = "\033[94m"  # Blue
    AGENT = "\033[92m"    # Green
    FRONTEND = "\033[93m" # Yellow
    YELLOW = "\033[93m"   # Yellow (alias)
    ERROR = "\033[91m"    # Red
    RESET = "\033[0m"     # Reset
    BOLD = "\033[1m"


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
        except FileNotFoundError as e:
            error_symbol = "X" if platform.system() == "Windows" else "✗"
            print(f"{Colors.ERROR}{error_symbol} Failed to start {self.config.name}: Command not found ({cmd[0]}){Colors.RESET}")
            print(f"   Make sure {cmd[0]} is installed and in PATH")
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
    
    def _run_health_checks(self):
        """Run health checks after services start."""
        health_check_script = self.project_root / "tools" / "commands" / "health-check.py"
        
        if not health_check_script.exists():
            # Health check script not available, skip
            return
        
        print(f"\n{Colors.BOLD}Running health checks...{Colors.RESET}")
        try:
            result = subprocess.run(
                [sys.executable, str(health_check_script), "--no-wait", "--max-wait", "15"],
                cwd=str(self.project_root),
                timeout=20,
                capture_output=False
            )
            # Don't fail startup if health check fails, just report
            if result.returncode != 0:
                print(f"{Colors.YELLOW}[WARN] Health checks reported issues. Check logs above.{Colors.RESET}")
        except subprocess.TimeoutExpired:
            print(f"{Colors.YELLOW}[WARN] Health check timed out. Services may still be initializing.{Colors.RESET}")
        except Exception as e:
            # Don't fail startup if health check fails
            print(f"{Colors.YELLOW}[WARN] Could not run health checks: {e}{Colors.RESET}")
    
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
        print(f"\n{Colors.BOLD}{success_symbol} All services started successfully!{Colors.RESET}")
        print(f"{Colors.BACKEND}Backend: http://localhost:8000{Colors.RESET}")
        print(f"{Colors.FRONTEND}Frontend: http://localhost:3000{Colors.RESET}")
        print(f"\nLogs are in the logs/ directory")
        
        # Run health checks after services start
        self._run_health_checks()
        
        print(f"Press Ctrl+C to stop all services\n")
        
        return True
    
    def _run_health_checks(self):
        """Run health checks after services start."""
        health_check_script = self.project_root / "tools" / "commands" / "health-check.py"
        
        if not health_check_script.exists():
            # Health check script not available, skip
            return
        
        print(f"\n{Colors.BOLD}Running health checks...{Colors.RESET}")
        try:
            result = subprocess.run(
                [sys.executable, str(health_check_script), "--no-wait", "--max-wait", "15"],
                cwd=str(self.project_root),
                timeout=20,
                capture_output=False
            )
            # Don't fail startup if health check fails, just report
            if result.returncode != 0:
                print(f"{Colors.YELLOW}[WARN] Health checks reported issues. Check logs above.{Colors.RESET}")
        except subprocess.TimeoutExpired:
            print(f"{Colors.YELLOW}[WARN] Health check timed out. Services may still be initializing.{Colors.RESET}")
        except Exception as e:
            # Don't fail startup if health check fails
            print(f"{Colors.YELLOW}[WARN] Could not run health checks: {e}{Colors.RESET}")
    
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
        log_file=logs_dir / "agent.log",
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
    
    # Install backend dependencies (quiet mode)
    backend_python = get_python_executable(backend_venv)
    backend_reqs = project_root / "backend" / "requirements.txt"
    if backend_reqs.exists():
        print(f"  Installing backend dependencies...")
        subprocess.run(
            [backend_python, "-m", "pip", "install", "-q", "-r", str(backend_reqs)],
            cwd=str(project_root / "backend"),
            check=False  # Don't fail if some packages fail
        )
    
    # Install agent dependencies (quiet mode)
    agent_python = get_python_executable(agent_venv)
    agent_reqs = project_root / "agent" / "requirements.txt"
    if agent_reqs.exists():
        print(f"  Installing agent dependencies...")
        subprocess.run(
            [agent_python, "-m", "pip", "install", "-q", "-r", str(agent_reqs)],
            cwd=str(project_root / "agent"),
            check=False  # Don't fail if some packages fail
        )
    
    # Check frontend node_modules
    frontend_dir = project_root / "frontend"
    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        print(f"  Installing frontend dependencies...")
        subprocess.run(
            [npm_cmd, "install"],
            cwd=str(frontend_dir),
            check=False  # Don't fail if npm install has warnings
        )
    
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


def check_prerequisites() -> bool:
    """Check if required services (PostgreSQL, Redis) are running.
    
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
    
    if not check_redis_running(redis_url):
        host, port = parse_redis_url(redis_url)
        issues.append(f"Redis is not accessible at {host}:{port}")
    
    if issues:
        print_prerequisite_error(issues)
        return False
    
    success_symbol = "OK" if platform.system() == "Windows" else "✓"
    print(f"{Colors.BOLD}{success_symbol} Prerequisites check passed{Colors.RESET}\n")
    return True


def run_validation_script(script_path: Path, script_name: str) -> bool:
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
            cwd=str(script_path.parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=30
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
    
    # Resolve npm command early (raises if missing)
    try:
        npm_cmd = get_npm_executable()
    except FileNotFoundError as exc:
        print(f"{Colors.ERROR}{exc}{Colors.RESET}")
        print(f"\n{Colors.BOLD}Please install Node.js 18+ and ensure npm is in your PATH{Colors.RESET}")
        sys.exit(1)

    # Load root .env so child processes inherit environment variables
    load_root_env(project_root)

    # Validate .env file contents before proceeding
    env_validator_path = project_root / "scripts" / "validate-env.py"
    if env_validator_path.exists():
        print(f"{Colors.BOLD}Validating environment variables...{Colors.RESET}")
        if not run_validation_script(env_validator_path, "validate-env.py"):
            print(f"\n{Colors.ERROR}Environment validation failed. Please fix .env file issues above.{Colors.RESET}")
            print(f"Run manually: python {env_validator_path}")
            sys.exit(1)
        print()  # Empty line after validation
    
    # Validate prerequisites (Python, Node.js, PostgreSQL, Redis)
    prereq_validator_path = project_root / "tools" / "commands" / "validate-prerequisites.py"
    if prereq_validator_path.exists():
        if not run_validation_script(prereq_validator_path, "validate-prerequisites.py"):
            print(f"\n{Colors.ERROR}Prerequisite validation failed. Please fix issues above.{Colors.RESET}")
            print(f"Run manually: python {prereq_validator_path}")
            sys.exit(1)
    else:
        # Fallback to built-in prerequisite check
        print(f"{Colors.BOLD}Checking prerequisites...{Colors.RESET}")
        if not check_prerequisites():
            sys.exit(1)

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
    
    # Setup and start services
    try:
        manager = setup_services(project_root, npm_cmd)
        
        if not manager.start_all():
            print(f"\n{Colors.ERROR}Failed to start services. Check logs above for details.{Colors.RESET}")
            print(f"\n{Colors.BOLD}Troubleshooting:{Colors.RESET}")
            print(f"  1. Check service logs in logs/ directory")
            print(f"  2. Verify all prerequisites are running (PostgreSQL, Redis)")
            print(f"  3. Ensure ports 8000, 3000, 8001 are available")
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

