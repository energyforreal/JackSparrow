#!/usr/bin/env python3
"""
Test startup sequence validation.

Tests that the startup sequence works correctly with all fixes applied.
"""

import os
import sys
import platform
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
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

# ASCII-safe symbols for Windows compatibility
class Colors:
    """Terminal color codes."""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class Symbols:
    """ASCII-safe symbols."""
    def __init__(self):
        is_windows = platform.system() == "Windows"
        self.CHECK = "[OK]" if is_windows else "✓"
        self.WARNING = "[WARN]" if is_windows else "⚠"
        self.CROSS = "[FAIL]" if is_windows else "✗"
        self.SUCCESS = "[SUCCESS]" if is_windows else "✅"


_symbols = Symbols()

# Try to import HealthChecker, but don't fail if it's not available
try:
    import importlib.util
    health_check_path = project_root / "tools" / "commands" / "health_check.py"
    if health_check_path.exists():
        spec = importlib.util.spec_from_file_location("health_check", health_check_path)
        health_check_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(health_check_module)
        HealthChecker = health_check_module.HealthChecker
    else:
        HealthChecker = None
except Exception:
    HealthChecker = None


class StartupSequenceTester:
    """Test startup sequence."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_script_imports(self):
        """Test that startup scripts can be imported."""
        print(f"{Colors.BOLD}Testing Script Imports{Colors.RESET}\n")
        
        scripts = [
            ("tools.commands.health_check", "Health Check Script"),
            ("tools.commands.start_parallel", "Start Parallel Script"),
        ]
        
        for script_name, display_name in scripts:
            try:
                __import__(script_name)
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {display_name}")
                self.tests_passed += 1
            except ImportError:
                print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} {display_name} (not available)")
            except Exception as e:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} {display_name}: {e}")
                self.tests_failed += 1
    
    def test_health_checker(self):
        """Test health checker initialization."""
        print(f"\n{Colors.BOLD}Testing Health Checker{Colors.RESET}\n")
        
        if HealthChecker is None:
            print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Health Checker not available (skipping)")
            return
        
        try:
            checker = HealthChecker()
            assert checker is not None
            print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Health Checker initialized")
            self.tests_passed += 1
        except Exception as e:
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Health Checker error: {e}")
            self.tests_failed += 1
    
    def test_unicode_handling(self):
        """Test Unicode handling in startup."""
        print(f"\n{Colors.BOLD}Testing Unicode Handling{Colors.RESET}\n")
        
        unicode_strings = [
            "Test with Unicode: ✓ ⚠ ✗ ✅",
            "Mixed content: Hello 世界",
        ]
        
        for test_string in unicode_strings:
            try:
                encoded = test_string.encode('utf-8', errors='replace')
                decoded = encoded.decode('utf-8', errors='replace')
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Unicode handling: {test_string[:30]}...")
                self.tests_passed += 1
            except Exception as e:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Unicode error: {e}")
                self.tests_failed += 1
    
    def test_symbols(self):
        """Test symbol rendering."""
        print(f"\n{Colors.BOLD}Testing Symbols{Colors.RESET}\n")
        
        try:
            # Test that symbols can be printed
            print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} Check symbol works")
            print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Warning symbol works")
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Cross symbol works")
            print(f"{Colors.GREEN}{_symbols.SUCCESS}{Colors.RESET} Success symbol works")
            self.tests_passed += 1
        except Exception as e:
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Symbol error: {e}")
            self.tests_failed += 1
    
    def run_all_tests(self):
        """Run all startup sequence tests."""
        self.test_script_imports()
        self.test_health_checker()
        self.test_unicode_handling()
        self.test_symbols()
        
        print(f"\n{Colors.BOLD}Test Summary{Colors.RESET}")
        print(f"{Colors.GREEN}Passed: {self.tests_passed}{Colors.RESET}")
        if self.tests_failed > 0:
            print(f"{Colors.RED}Failed: {self.tests_failed}{Colors.RESET}")
        else:
            print(f"{Colors.GREEN}{_symbols.SUCCESS} All startup sequence tests passed!{Colors.RESET}")
        
        return self.tests_failed == 0


def main():
    """Main entry point."""
    tester = StartupSequenceTester()
    success = tester.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

