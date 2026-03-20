#!/usr/bin/env python3
"""
Run all tests related to recent fixes.

Automates test execution for:
- Unicode encoding tests
- Event deserialization tests
- XGBoost compatibility tests
- Corrupted model handling tests
- Error handling tests
"""

import os
import sys
import subprocess
import platform
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


class TestRunner:
    """Test runner for fix-related tests."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.test_results = {}
        self.tests_skipped = 0
    
    def run_pytest_tests(self, test_path: str, test_name: str) -> bool:
        """Run pytest tests.
        
        Args:
            test_path: Path to test file or directory
            test_name: Display name for the test
            
        Returns:
            True if all tests passed, False otherwise
        """
        print(f"\n{Colors.BOLD}Running {test_name}...{Colors.RESET}")
        
        test_file = self.project_root / test_path
        
        if not test_file.exists():
            print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} Test file not found (skipping): {test_path}")
            self.test_results[test_name] = "skipped"
            self.tests_skipped += 1
            return True
        
        try:
            # Run pytest
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-v"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {test_name} passed")
                self.test_results[test_name] = True
                return True
            else:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} {test_name} failed")
                print(result.stdout)
                print(result.stderr)
                self.test_results[test_name] = False
                return False
        except Exception as e:
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} Error running {test_name}: {e}")
            self.test_results[test_name] = False
            return False
    
    def run_all_tests(self):
        """Run all fix-related tests."""
        print(f"{Colors.BOLD}Running Fix-Related Tests{Colors.RESET}\n")
        
        tests = [
            ("tests/unit/trading_agent_tests/test_event_bus_deserialization.py", "Event Bus Deserialization Tests"),
            ("tests/unit/trading_agent_tests/test_xgboost_node.py", "XGBoost Node Tests"),
            ("tests/unit/tools/test_unicode_encoding.py", "Unicode Encoding Tests"),
            ("tests/unit/trading_agent_tests/test_model_discovery.py", "Model Discovery Tests"),
            ("tests/integration/test_event_pipeline.py", "Event Pipeline Integration Tests"),
            ("tests/integration/test_model_loading.py", "Model Loading Integration Tests"),
            ("tests/integration/test_startup_scripts.py", "Startup Scripts Integration Tests"),
        ]
        
        passed = 0
        failed = 0
        
        for test_path, test_name in tests:
            if self.run_pytest_tests(test_path, test_name):
                passed += 1
            else:
                failed += 1
        
        # Print summary
        print(f"\n{Colors.BOLD}Test Summary{Colors.RESET}")
        print(f"{Colors.GREEN}Passed: {passed}{Colors.RESET}")
        if self.tests_skipped:
            print(f"{Colors.YELLOW}Skipped: {self.tests_skipped}{Colors.RESET}")
        if failed > 0:
            print(f"{Colors.RED}Failed: {failed}{Colors.RESET}")
        else:
            print(f"{Colors.GREEN}{_symbols.SUCCESS} All tests passed!{Colors.RESET}")
        
        return failed == 0


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run all fix-related tests")
    parser.add_argument("--test", help="Run specific test file")
    
    args = parser.parse_args()
    
    runner = TestRunner()
    
    if args.test:
        # Run specific test
        success = runner.run_pytest_tests(args.test, args.test)
    else:
        # Run all tests
        success = runner.run_all_tests()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

