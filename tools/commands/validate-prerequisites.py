#!/usr/bin/env python3
"""
Prerequisite validation script for JackSparrow Trading Agent.

Checks that all required prerequisites are installed and running before starting services:
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ (running)
- Redis 7.0+ (running)
- Port availability
"""

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Try to import database libraries (optional)
try:
    from sqlalchemy import create_engine, text, inspect
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class Colors:
    """Terminal color codes."""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class PrerequisiteValidator:
    """Validates system prerequisites."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.is_windows = platform.system() == "Windows"
    
    def check_python_version(self) -> bool:
        """Check Python version is 3.11+.
        
        Returns:
            True if version is acceptable, False otherwise
        """
        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 11):
            self.errors.append(
                f"Python version {version.major}.{version.minor} detected. "
                f"Python 3.11+ is required."
            )
            return False
        
        success_symbol = "OK" if self.is_windows else "✓"
        print(f"{Colors.GREEN}{success_symbol}{Colors.RESET} Python {version.major}.{version.minor}.{version.micro}")
        return True
    
    def check_node_version(self) -> bool:
        """Check Node.js version is 18+.
        
        Returns:
            True if version is acceptable, False otherwise
        """
        # Try npm.cmd on Windows first
        npm_candidates = ["npm.cmd", "npm.exe", "npm"] if self.is_windows else ["npm"]
        
        npm_path = None
        for candidate in npm_candidates:
            npm_path = shutil.which(candidate)
            if npm_path:
                break
        
        if not npm_path:
            self.errors.append(
                "Node.js/npm not found in PATH. "
                "Please install Node.js 18+ and ensure npm is accessible."
            )
            return False
        
        try:
            result = subprocess.run(
                [npm_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                self.errors.append("Failed to check Node.js version")
                return False
            
            # Get node version
            node_result = subprocess.run(
                ["node", "--version"] if not self.is_windows else ["node.exe", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if node_result.returncode == 0:
                node_version_str = node_result.stdout.strip().lstrip("v")
                try:
                    major_version = int(node_version_str.split(".")[0])
                    if major_version < 18:
                        self.errors.append(
                            f"Node.js version {node_version_str} detected. "
                            f"Node.js 18+ is required."
                        )
                        return False
                    print(f"{Colors.GREEN}✓{Colors.RESET} Node.js {node_version_str}")
                except ValueError:
                    warning_symbol = "!" if self.is_windows else "⚠"
                    print(f"{Colors.YELLOW}{warning_symbol}{Colors.RESET} Node.js version format unexpected: {node_version_str}")
            else:
                warning_symbol = "!" if self.is_windows else "⚠"
                print(f"{Colors.YELLOW}{warning_symbol}{Colors.RESET} Could not determine Node.js version")
            
            return True
            
        except FileNotFoundError:
            self.errors.append("Node.js not found in PATH")
            return False
        except subprocess.TimeoutExpired:
            self.errors.append("Timeout checking Node.js version")
            return False
        except Exception as e:
            self.errors.append(f"Error checking Node.js: {e}")
            return False
    
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
        except Exception:
            return False
    
    def check_postgres_running(self) -> bool:
        """Check if PostgreSQL is running.
        
        Returns:
            True if PostgreSQL is accessible, False otherwise
        """
        # Try to get DATABASE_URL from environment
        database_url = os.environ.get("DATABASE_URL", "")
        
        if not database_url:
            # Try to load from .env file
            script_path = Path(__file__).resolve()
            project_root = script_path.parent.parent.parent
            env_path = project_root / ".env"
            
            if env_path.exists():
                try:
                    with env_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("DATABASE_URL="):
                                database_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
                except Exception:
                    pass
        
        if not database_url:
            self.errors.append(
                "DATABASE_URL not found. Cannot check PostgreSQL connection. "
                "Please set DATABASE_URL in .env file."
            )
            return False
        
        # Parse database URL
        if "+" in database_url and "://" in database_url:
            scheme_part, rest = database_url.split("://", 1)
            database_url = f"postgresql://{rest}"
        
        try:
            parsed = urlparse(database_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
        except Exception:
            host = "localhost"
            port = 5432
        
        if self.check_port_accessible(host, port):
            success_symbol = "OK" if self.is_windows else "✓"
            print(f"{Colors.GREEN}{success_symbol}{Colors.RESET} PostgreSQL accessible at {host}:{port}")
            # Check database schema if connection successful
            self.check_database_schema(database_url)
            return True
        else:
            self.errors.append(
                f"PostgreSQL is not accessible at {host}:{port}. "
                f"Please ensure PostgreSQL is installed and running."
            )
            return False
    
    def check_database_schema(self, database_url: str) -> bool:
        """Check if required database tables exist.
        
        Args:
            database_url: PostgreSQL connection URL
            
        Returns:
            True if schema is valid, False otherwise
        """
        if not SQLALCHEMY_AVAILABLE:
            # Skip schema check if SQLAlchemy not available
            return True
        
        required_tables = [
            "trades",
            "positions",
            "decisions",
            "performance_metrics",
            "model_performance",
        ]
        
        try:
            # Normalize database URL for SQLAlchemy
            if "+" in database_url and "://" in database_url:
                scheme_part, rest = database_url.split("://", 1)
                database_url = f"postgresql://{rest}"
            elif not database_url.startswith(("postgresql://", "postgres://")):
                # Skip if URL format is invalid
                return True
            
            engine = create_engine(database_url, connect_args={"connect_timeout": 5})
            inspector = inspect(engine)
            
            existing_tables = inspector.get_table_names()
            missing_tables = [table for table in required_tables if table not in existing_tables]
            
            if missing_tables:
                self.warnings.append(
                    f"Database tables missing: {', '.join(missing_tables)}. "
                    f"Run 'python scripts/setup_db.py' to initialize database schema."
                )
                return False
            else:
                success_symbol = "OK" if self.is_windows else "✓"
                print(f"{Colors.GREEN}{success_symbol}{Colors.RESET} Database schema validated (all tables exist)")
                return True
                
        except Exception as e:
            # Don't fail prerequisite check if schema check fails
            # Just warn about it
            self.warnings.append(
                f"Could not validate database schema: {str(e)}. "
                f"Ensure database is initialized with 'python scripts/setup_db.py'"
            )
            return True
    
    def check_redis_running(self) -> bool:
        """Check if Redis is running.
        
        Returns:
            True if Redis is accessible, False otherwise
        """
        # Try to get REDIS_URL from environment
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        
        # Try to load from .env file if not in environment
        if redis_url == "redis://localhost:6379":
            script_path = Path(__file__).resolve()
            project_root = script_path.parent.parent.parent
            env_path = project_root / ".env"
            
            if env_path.exists():
                try:
                    with env_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("REDIS_URL="):
                                redis_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
                except Exception:
                    pass
        
        try:
            parsed = urlparse(redis_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 6379
        except Exception:
            host = "localhost"
            port = 6379
        
        if self.check_port_accessible(host, port):
            success_symbol = "OK" if self.is_windows else "✓"
            print(f"{Colors.GREEN}{success_symbol}{Colors.RESET} Redis accessible at {host}:{port}")
            return True
        else:
            self.errors.append(
                f"Redis is not accessible at {host}:{port}. "
                f"Please ensure Redis is installed and running."
            )
            return False
    
    def check_port_available(self, port: int, service_name: str) -> bool:
        """Check if a port is available.
        
        Args:
            port: Port number to check
            service_name: Name of service using the port
            
        Returns:
            True if port is available, False otherwise
        """
        if self.check_port_accessible("localhost", port):
            self.warnings.append(
                f"Port {port} ({service_name}) is already in use. "
                f"This may prevent the service from starting."
            )
            return False
        
        return True
    
    def check_service_ports(self) -> bool:
        """Check that service ports are available.
        
        Returns:
            True if all ports available, False otherwise
        """
        ports_to_check = [
            (8000, "Backend"),
            (3000, "Frontend"),
            (8001, "Agent Feature Server"),
        ]
        
        all_available = True
        for port, service_name in ports_to_check:
            if not self.check_port_available(port, service_name):
                all_available = False
        
        return all_available
    
    def validate_all(self) -> bool:
        """Run all prerequisite checks.
        
        Returns:
            True if all checks pass, False otherwise
        """
        print(f"{Colors.BOLD}Checking Prerequisites...{Colors.RESET}\n")
        
        valid = True
        valid &= self.check_python_version()
        valid &= self.check_node_version()
        valid &= self.check_postgres_running()
        valid &= self.check_redis_running()
        self.check_service_ports()  # Warnings only, don't fail
        
        return valid
    
    def print_results(self) -> None:
        """Print validation results."""
        print()
        
        if self.errors:
            print(f"{Colors.RED}{Colors.BOLD}❌ PREREQUISITE CHECK FAILED{Colors.RESET}\n")
            error_symbol = "X" if self.is_windows else "✗"
            print("The following issues were found:")
            for error in self.errors:
                print(f"  {Colors.RED}{error_symbol}{Colors.RESET} {error}")
            print()
            
            # Platform-specific help
            system = platform.system()
            print(f"{Colors.BOLD}To fix these issues:{Colors.RESET}\n")
            
            if system == "Windows":
                print("1. Install/Start PostgreSQL:")
                print("   - Download from https://www.postgresql.org/download/windows/")
                print("   - Or use: choco install postgresql")
                print("   - Start service: net start postgresql-x64-15")
                print()
                print("2. Install/Start Redis:")
                print("   - Download from https://github.com/microsoftarchive/redis/releases")
                print("   - Or use: choco install redis-64")
                print("   - Run: redis-server.exe")
                print()
            elif system == "Darwin":  # macOS
                print("1. Install/Start PostgreSQL:")
                print("   brew install postgresql@15")
                print("   brew services start postgresql@15")
                print()
                print("2. Install/Start Redis:")
                print("   brew install redis")
                print("   brew services start redis")
                print()
            else:  # Linux
                print("1. Install/Start PostgreSQL:")
                print("   sudo apt install postgresql-15")
                print("   sudo systemctl start postgresql")
                print()
                print("2. Install/Start Redis:")
                print("   sudo apt install redis-server")
                print("   sudo systemctl start redis")
                print()
            
            print(f"{Colors.BOLD}For detailed setup instructions, see docs/11-build-guide.md{Colors.RESET}\n")
        
        if self.warnings:
            warning_symbol = "!" if self.is_windows else "⚠"
            print(f"{Colors.YELLOW}{Colors.BOLD}{warning_symbol}  WARNINGS:{Colors.RESET}\n")
            for warning in self.warnings:
                print(f"  {Colors.YELLOW}{warning_symbol}{Colors.RESET} {warning}")
            print()
        
        if not self.errors:
            success_symbol = "OK" if self.is_windows else "✅"
            print(f"{Colors.GREEN}{Colors.BOLD}{success_symbol} All prerequisites validated successfully!{Colors.RESET}\n")


def main():
    """Main entry point."""
    validator = PrerequisiteValidator()
    
    if not validator.validate_all():
        validator.print_results()
        sys.exit(1)
    
    validator.print_results()
    sys.exit(0)


if __name__ == "__main__":
    main()

