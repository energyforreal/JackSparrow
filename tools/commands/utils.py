#!/usr/bin/env python3
"""
Shared utilities for JackSparrow command-line tools.

This module contains common utilities, constants, and helper functions
used across multiple command-line scripts.
"""

import os
import sys
import platform
import shutil
import socket
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse


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


def _flushed_print(*args, **kwargs):
    """Proxy print that always flushes stdout (and stderr when used)."""
    kwargs.setdefault("flush", True)
    builtins.print(*args, **kwargs)


# Ensure every existing print() call in this module flushes immediately.
builtins = __import__('builtins')
print = _flushed_print  # type: ignore


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
            "npm executable not found. Install Node.js 18+ and ensure npm is in your PATH."
        )
    return path


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
        return False
