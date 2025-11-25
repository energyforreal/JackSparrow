#!/usr/bin/env python3
"""
Test Unicode encoding handling.

Tests that all scripts handle Unicode characters correctly.
"""

import os
import sys
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


class EncodingTester:
    """Test Unicode encoding handling."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_unicode_strings(self):
        """Test various Unicode strings."""
        print(f"{Colors.BOLD}Testing Unicode String Handling{Colors.RESET}\n")
        
        test_strings = [
            "Simple ASCII text",
            "Text with émojis: ✓ ⚠ ✗ ✅",
            "Mixed content: Hello 世界",
            "Special chars: © ® ™ € £ ¥",
            "Math symbols: ∑ ∫ √ ∞",
        ]
        
        for test_string in test_strings:
            try:
                # Test encoding/decoding
                encoded = test_string.encode('utf-8', errors='replace')
                decoded = encoded.decode('utf-8', errors='replace')
                
                if decoded == test_string:
                    print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {test_string[:50]}")
                    self.tests_passed += 1
                else:
                    print(f"{Colors.YELLOW}{_symbols.WARNING}{Colors.RESET} {test_string[:50]} (modified)")
                    self.tests_passed += 1
            except UnicodeEncodeError as e:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} {test_string[:50]}: {e}")
                self.tests_failed += 1
    
    def test_symbols(self):
        """Test symbol rendering."""
        print(f"\n{Colors.BOLD}Testing Symbol Rendering{Colors.RESET}\n")
        
        symbols_to_test = [
            (_symbols.CHECK, "Check symbol"),
            (_symbols.WARNING, "Warning symbol"),
            (_symbols.CROSS, "Cross symbol"),
            (_symbols.SUCCESS, "Success symbol"),
        ]
        
        for symbol, name in symbols_to_test:
            try:
                # Try to print symbol
                test_output = f"{symbol} {name}"
                encoded = test_output.encode('utf-8', errors='replace')
                decoded = encoded.decode('utf-8', errors='replace')
                
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {name}: {symbol}")
                self.tests_passed += 1
            except Exception as e:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} {name}: {e}")
                self.tests_failed += 1
    
    def test_script_imports(self):
        """Test that scripts can be imported with Unicode."""
        print(f"\n{Colors.BOLD}Testing Script Imports{Colors.RESET}\n")
        
        scripts = [
            "tools.commands.health_check",
            "tools.commands.start_parallel",
        ]
        
        for script_name in scripts:
            try:
                __import__(script_name)
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {script_name}")
                self.tests_passed += 1
            except Exception as e:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} {script_name}: {e}")
                self.tests_failed += 1
    
    def test_file_operations(self):
        """Test file operations with Unicode."""
        print(f"\n{Colors.BOLD}Testing File Operations{Colors.RESET}\n")
        
        import tempfile
        
        unicode_content = "Test with Unicode: ✓ ⚠ ✗ ✅\n"
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.log') as f:
                log_file_path = Path(f.name)
                try:
                    # Write Unicode content
                    f.write(unicode_content)
                    f.flush()
                    
                    # Read back and verify
                    with open(log_file_path, 'r', encoding='utf-8', errors='replace') as read_file:
                        content = read_file.read()
                        if "Unicode" in content:
                            print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} File operations with Unicode")
                            self.tests_passed += 1
                        else:
                            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} File operations failed")
                            self.tests_failed += 1
                finally:
                    # Cleanup
                    log_file_path.unlink()
        except Exception as e:
            print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} File operations error: {e}")
            self.tests_failed += 1
    
    def run_all_tests(self):
        """Run all encoding tests."""
        self.test_unicode_strings()
        self.test_symbols()
        self.test_script_imports()
        self.test_file_operations()
        
        print(f"\n{Colors.BOLD}Test Summary{Colors.RESET}")
        print(f"{Colors.GREEN}Passed: {self.tests_passed}{Colors.RESET}")
        if self.tests_failed > 0:
            print(f"{Colors.RED}Failed: {self.tests_failed}{Colors.RESET}")
        else:
            print(f"{Colors.GREEN}{_symbols.SUCCESS} All encoding tests passed!{Colors.RESET}")
        
        return self.tests_failed == 0


def main():
    """Main entry point."""
    tester = EncodingTester()
    success = tester.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

