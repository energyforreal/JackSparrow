#!/usr/bin/env python3
"""
Database connection diagnostic script for JackSparrow Trading Agent.

Diagnoses PostgreSQL connection issues and provides specific solutions.
"""

import os
import sys
import platform
from pathlib import Path
from urllib.parse import urlparse, quote, unquote

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv


class Colors:
    """Terminal color codes."""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def mask_password(url: str) -> str:
    """Mask password in database URL for display."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            masked_url = url.replace(f":{parsed.password}@", ":***@")
            return masked_url
        return url
    except Exception:
        return url.replace("://", "://***:***@")


def diagnose_database_connection():
    """Diagnose database connection issues."""
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}Database Connection Diagnostic{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")
    
    # Load .env file
    env_path = project_root / ".env"
    if not env_path.exists():
        print(f"{Colors.RED}ERROR: .env file not found at {env_path}{Colors.RESET}")
        sys.exit(1)
    
    print(f"{Colors.BLUE}Step 1: Loading .env file...{Colors.RESET}")
    load_dotenv(dotenv_path=env_path)
    print(f"{Colors.GREEN}✓ .env file loaded{Colors.RESET}\n")
    
    # Get DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print(f"{Colors.RED}ERROR: DATABASE_URL not found in environment variables{Colors.RESET}")
        print(f"Please set DATABASE_URL in the .env file")
        sys.exit(1)
    
    print(f"{Colors.BLUE}Step 2: Parsing DATABASE_URL...{Colors.RESET}")
    print(f"  DATABASE_URL: {mask_password(database_url)}")
    
    # Parse URL
    try:
        # Handle postgresql+asyncpg:// format
        if "+" in database_url and "://" in database_url:
            scheme_part, rest = database_url.split("://", 1)
            url_to_parse = f"postgresql://{rest}"
        else:
            url_to_parse = database_url
        
        parsed = urlparse(url_to_parse)
        
        username = parsed.username or ""
        password = parsed.password or ""
        hostname = parsed.hostname or "localhost"
        port = parsed.port or 5432
        database = parsed.path.lstrip("/") if parsed.path else ""
        
        print(f"  Username: {username}")
        print(f"  Password: {'***' if password else '(not set)'}")
        print(f"  Hostname: {hostname}")
        print(f"  Port: {port}")
        print(f"  Database: {database}")
        print(f"{Colors.GREEN}✓ URL format is valid{Colors.RESET}\n")
        
    except Exception as e:
        print(f"{Colors.RED}✗ URL parsing failed: {e}{Colors.RESET}")
        sys.exit(1)
    
    # Check for common issues
    print(f"{Colors.BLUE}Step 3: Checking for common issues...{Colors.RESET}")
    issues = []
    
    if not username:
        issues.append("Username is missing")
    if not password:
        issues.append("Password is missing")
    if not database:
        issues.append("Database name is missing")
    
    # Check for special characters that might need encoding
    if password:
        special_chars = ['@', '#', '%', '&', '?', '=', '+']
        needs_encoding = any(char in password for char in special_chars)
        if needs_encoding:
            issues.append("Password contains special characters that may need URL encoding")
            print(f"  {Colors.YELLOW}⚠ Password contains special characters{Colors.RESET}")
            print(f"  If connection fails, try URL encoding: {quote(password)}{Colors.RESET}")
    
    if issues:
        print(f"{Colors.YELLOW}⚠ Found {len(issues)} potential issue(s):{Colors.RESET}")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"{Colors.GREEN}✓ No obvious format issues found{Colors.RESET}")
    print()
    
    # Test connection
    print(f"{Colors.BLUE}Step 4: Testing PostgreSQL connection...{Colors.RESET}")
    
    try:
        import psycopg2
        PSYCOPG2_AVAILABLE = True
    except ImportError:
        PSYCOPG2_AVAILABLE = False
        print(f"{Colors.YELLOW}⚠ psycopg2 not available, skipping connection test{Colors.RESET}")
        print(f"  Install with: pip install psycopg2-binary")
    
    if PSYCOPG2_AVAILABLE:
        try:
            # Test connection
            conn = psycopg2.connect(
                host=hostname,
                port=port,
                user=username,
                password=password,
                database=database,
                connect_timeout=5
            )
            conn.close()
            print(f"{Colors.GREEN}✓ Connection successful!{Colors.RESET}\n")
            return True
            
        except psycopg2.OperationalError as e:
            error_msg = str(e)
            print(f"{Colors.RED}✗ Connection failed: {error_msg}{Colors.RESET}\n")
            
            # Provide specific solutions based on error
            if "password authentication failed" in error_msg.lower():
                print(f"{Colors.BOLD}Solution:{Colors.RESET}")
                print(f"  The user '{username}' either doesn't exist or the password is incorrect.")
                print(f"\n  To create the user and database:")
                print(f"  1. Connect as postgres superuser:")
                print(f"     psql -U postgres -h {hostname}")
                print(f"  2. Run these SQL commands:")
                print(f"     CREATE USER {username} WITH PASSWORD '{password}';")
                print(f"     CREATE DATABASE {database} OWNER {username};")
                print(f"     GRANT ALL PRIVILEGES ON DATABASE {database} TO {username};")
                print(f"     \\c {database}")
                print(f"     GRANT ALL ON SCHEMA public TO {username};")
                
            elif "does not exist" in error_msg.lower():
                if "database" in error_msg.lower():
                    print(f"{Colors.BOLD}Solution:{Colors.RESET}")
                    print(f"  The database '{database}' doesn't exist.")
                    print(f"  Create it with:")
                    print(f"    psql -U postgres -h {hostname} -c \"CREATE DATABASE {database} OWNER {username};\"")
                elif "role" in error_msg.lower() or "user" in error_msg.lower():
                    print(f"{Colors.BOLD}Solution:{Colors.RESET}")
                    print(f"  The user '{username}' doesn't exist.")
                    print(f"  Create it with:")
                    print(f"    psql -U postgres -h {hostname} -c \"CREATE USER {username} WITH PASSWORD '{password}';\"")
            
            elif "could not connect" in error_msg.lower():
                print(f"{Colors.BOLD}Solution:{Colors.RESET}")
                print(f"  Cannot connect to PostgreSQL server at {hostname}:{port}")
                print(f"  Ensure PostgreSQL is running:")
                print(f"    Get-Service postgresql* | Start-Service")
            
            return False
            
        except Exception as e:
            print(f"{Colors.RED}✗ Unexpected error: {e}{Colors.RESET}\n")
            return False
    
    return False


def main():
    """Main entry point."""
    success = diagnose_database_connection()
    
    if success:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ All checks passed! Database connection is working.{Colors.RESET}\n")
        sys.exit(0)
    else:
        print(f"{Colors.RED}{Colors.BOLD}✗ Database connection diagnostic found issues.{Colors.RESET}")
        print(f"Please follow the solutions above to fix the connection.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

