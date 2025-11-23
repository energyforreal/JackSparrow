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
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes for service identification."""
    BACKEND = "\033[94m"  # Blue
    AGENT = "\033[92m"    # Green
    FRONTEND = "\033[93m" # Yellow
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
            
            # Start process
            self.process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            
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
            
        except Exception as e:
            print(f"{Colors.ERROR}✗ Failed to start {self.config.name}: {e}{Colors.RESET}")
            return False
    
    def _stream_logs(self):
        """Stream logs from process stdout to console and file."""
        log_file_handle = None
        if self.config.log_file:
            log_file_handle = open(self.config.log_file, 'w', encoding='utf-8')
        
        try:
            if self.process and self.process.stdout:
                for line in iter(self.process.stdout.readline, ''):
                    if not line:
                        break
                    
                    # Write to log file
                    if log_file_handle:
                        log_file_handle.write(line)
                        log_file_handle.flush()
                    
                    # Print to console with service prefix
                    prefix = f"{self.config.color}[{self.config.name}]{Colors.RESET}"
                    print(f"{prefix} {line.rstrip()}")
                    
        except Exception as e:
            print(f"{Colors.ERROR}Log streaming error for {self.config.name}: {e}{Colors.RESET}")
        finally:
            if log_file_handle:
                log_file_handle.close()
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
        for name, manager in self.services.items():
            print(f"{Colors.BOLD}Starting {name}...{Colors.RESET}")
            if manager.start():
                started_services.append(name)
            else:
                print(f"{Colors.ERROR}✗ {name} failed to start{Colors.RESET}")
        
        if not started_services:
            print(f"{Colors.ERROR}No services started successfully{Colors.RESET}")
            return False
        
        # Wait a bit for processes to initialize
        time.sleep(self.services[started_services[0]].config.check_delay)
        
        # Check if all started services are still alive
        all_alive = True
        for name in started_services:
            if not self.services[name].is_alive():
                print(f"{Colors.ERROR}✗ {name} process died shortly after startup{Colors.RESET}")
                all_alive = False
        
        if all_alive:
            print(f"\n{Colors.BOLD}All services started successfully!{Colors.RESET}")
            print(f"{Colors.BACKEND}Backend: http://localhost:8000{Colors.RESET}")
            print(f"{Colors.FRONTEND}Frontend: http://localhost:3000{Colors.RESET}")
            print(f"\nLogs are in the logs/ directory")
            print(f"Press Ctrl+C to stop all services\n")
        else:
            print(f"\n{Colors.ERROR}Some services failed to start. Check logs for details.{Colors.RESET}")
            return False
        
        return True
    
    def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        try:
            while not self.shutdown_event.is_set():
                # Check if any service died unexpectedly
                for name, manager in self.services.items():
                    if manager.running and not manager.is_alive():
                        print(f"\n{Colors.ERROR}✗ {name} process died unexpectedly{Colors.RESET}")
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
        sys.exit(1)

    # Load root .env so child processes inherit environment variables
    load_root_env(project_root)

    # Ensure dependencies are set up
    try:
        ensure_dependencies(project_root, npm_cmd)
    except Exception as e:
        print(f"{Colors.ERROR}Error setting up dependencies: {e}{Colors.RESET}")
        print(f"Please ensure Python, Node.js, and npm are installed and accessible.")
        sys.exit(1)
    
    # Setup and start services
    manager = setup_services(project_root, npm_cmd)
    
    if not manager.start_all():
        sys.exit(1)
    
    # Wait for shutdown signal
    try:
        manager.wait_for_shutdown()
    except KeyboardInterrupt:
        manager.stop_all()
        sys.exit(0)


if __name__ == "__main__":
    main()

