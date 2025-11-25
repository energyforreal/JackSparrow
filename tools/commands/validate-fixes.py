#!/usr/bin/env python3
"""
Validation script for all recent fixes.

Validates:
- Unicode encoding error handling
- Event deserialization improvements
- XGBoost model compatibility warnings
- Corrupted model file handling
- Enhanced error handling
"""

import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

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


class FixValidator:
    """Validator for all recent fixes."""
    
    def __init__(self):
        self.results: Dict[str, Tuple[bool, str]] = {}
        self.project_root = Path(__file__).parent.parent.parent
    
    def validate_unicode_encoding(self) -> Tuple[bool, str]:
        """Validate Unicode encoding fixes."""
        try:
            # Test that health_check.py uses ASCII-safe symbols on Windows
            health_check_path = self.project_root / "tools" / "commands" / "health_check.py"
            if not health_check_path.exists():
                return False, "health_check.py not found"
            
            content = health_check_path.read_text(encoding='utf-8')
            
            # Check for platform-specific symbol handling
            if 'platform.system() == "Windows"' in content:
                if '[OK]' in content or '[WARN]' in content:
                    return True, "Unicode encoding fixes found in health_check.py"
            
            # Test start_parallel.py
            start_parallel_path = self.project_root / "tools" / "commands" / "start_parallel.py"
            if start_parallel_path.exists():
                content = start_parallel_path.read_text(encoding='utf-8')
                if 'reconfigure(encoding=\'utf-8\')' in content:
                    return True, "UTF-8 encoding configuration found in start_parallel.py"
            
            return False, "Unicode encoding fixes not found"
        except Exception as e:
            return False, f"Error validating Unicode encoding: {e}"
    
    def validate_event_deserialization(self) -> Tuple[bool, str]:
        """Validate event deserialization improvements."""
        try:
            event_bus_path = self.project_root / "agent" / "events" / "event_bus.py"
            if not event_bus_path.exists():
                return False, "event_bus.py not found"
            
            content = event_bus_path.read_text(encoding='utf-8')
            
            # Check for improved deserialization logic
            checks = [
                'key_variant in [b"event"',
                'event_json_bytes.decode("utf-8")',
                'event_instantiation_failed',
                'event_deserialization_failed'
            ]
            
            found_checks = sum(1 for check in checks if check in content)
            
            if found_checks >= 2:
                return True, f"Event deserialization improvements found ({found_checks} checks)"
            else:
                return False, f"Event deserialization improvements not found (only {found_checks} checks)"
        except Exception as e:
            return False, f"Error validating event deserialization: {e}"
    
    def validate_xgboost_compatibility(self) -> Tuple[bool, str]:
        """Validate XGBoost compatibility warning handling."""
        try:
            xgboost_node_path = self.project_root / "agent" / "models" / "xgboost_node.py"
            if not xgboost_node_path.exists():
                return False, "xgboost_node.py not found"
            
            content = xgboost_node_path.read_text(encoding='utf-8')
            
            # Check for warning capture and logging
            checks = [
                'warnings.catch_warnings',
                'xgboost_model_compatibility_warning',
                'serialized with an older XGBoost version'
            ]
            
            found_checks = sum(1 for check in checks if check in content)
            
            if found_checks >= 2:
                return True, f"XGBoost compatibility handling found ({found_checks} checks)"
            else:
                return False, f"XGBoost compatibility handling not found (only {found_checks} checks)"
        except Exception as e:
            return False, f"Error validating XGBoost compatibility: {e}"
    
    def validate_corrupted_model_handling(self) -> Tuple[bool, str]:
        """Validate corrupted model file handling."""
        try:
            xgboost_node_path = self.project_root / "agent" / "models" / "xgboost_node.py"
            model_discovery_path = self.project_root / "agent" / "models" / "model_discovery.py"
            
            if not xgboost_node_path.exists():
                return False, "xgboost_node.py not found"
            if not model_discovery_path.exists():
                return False, "model_discovery.py not found"
            
            xgboost_content = xgboost_node_path.read_text(encoding='utf-8')
            discovery_content = model_discovery_path.read_text(encoding='utf-8')
            
            # Check for corrupted file handling
            checks = [
                'file_size == 0',
                'corrupted',
                'invalid load key',
                'model_discovery_corrupted_file'
            ]
            
            xgboost_checks = sum(1 for check in checks if check in xgboost_content)
            discovery_checks = sum(1 for check in checks if check in discovery_content)
            
            if xgboost_checks >= 2 or discovery_checks >= 1:
                return True, f"Corrupted model handling found (xgboost: {xgboost_checks}, discovery: {discovery_checks})"
            else:
                return False, f"Corrupted model handling not found"
        except Exception as e:
            return False, f"Error validating corrupted model handling: {e}"
    
    def validate_error_handling(self) -> Tuple[bool, str]:
        """Validate enhanced error handling."""
        try:
            event_bus_path = self.project_root / "agent" / "events" / "event_bus.py"
            start_parallel_path = self.project_root / "tools" / "commands" / "start_parallel.py"
            
            if not event_bus_path.exists():
                return False, "event_bus.py not found"
            if not start_parallel_path.exists():
                return False, "start_parallel.py not found"
            
            event_bus_content = event_bus_path.read_text(encoding='utf-8')
            start_parallel_content = start_parallel_path.read_text(encoding='utf-8')
            
            # Check for comprehensive error handling
            checks = [
                'try:',
                'except Exception',
                'exc_info=True',
                'errors=\'replace\''
            ]
            
            event_bus_checks = sum(1 for check in checks if check in event_bus_content)
            start_parallel_checks = sum(1 for check in checks if check in start_parallel_content)
            
            if event_bus_checks >= 3 and start_parallel_checks >= 2:
                return True, f"Enhanced error handling found (event_bus: {event_bus_checks}, start_parallel: {start_parallel_checks})"
            else:
                return False, f"Enhanced error handling not sufficient"
        except Exception as e:
            return False, f"Error validating error handling: {e}"
    
    def run_all_validations(self) -> Dict[str, Tuple[bool, str]]:
        """Run all validations."""
        print(f"{Colors.BOLD}Running Fix Validations...{Colors.RESET}\n")
        
        validations = [
            ("Unicode Encoding", self.validate_unicode_encoding),
            ("Event Deserialization", self.validate_event_deserialization),
            ("XGBoost Compatibility", self.validate_xgboost_compatibility),
            ("Corrupted Model Handling", self.validate_corrupted_model_handling),
            ("Error Handling", self.validate_error_handling),
        ]
        
        for name, validation_func in validations:
            print(f"Validating {name}...", end=" ")
            success, message = validation_func()
            self.results[name] = (success, message)
            
            if success:
                print(f"{Colors.GREEN}{_symbols.CHECK}{Colors.RESET} {message}")
            else:
                print(f"{Colors.RED}{_symbols.CROSS}{Colors.RESET} {message}")
        
        return self.results
    
    def print_summary(self):
        """Print validation summary."""
        print(f"\n{Colors.BOLD}Validation Summary{Colors.RESET}\n")
        
        passed = sum(1 for success, _ in self.results.values() if success)
        total = len(self.results)
        
        for name, (success, message) in self.results.items():
            symbol = _symbols.CHECK if success else _symbols.CROSS
            color = Colors.GREEN if success else Colors.RED
            print(f"{color}{symbol}{Colors.RESET} {name}: {message}")
        
        print(f"\n{Colors.BOLD}Results: {passed}/{total} validations passed{Colors.RESET}")
        
        if passed == total:
            print(f"{Colors.GREEN}{_symbols.SUCCESS} All validations passed!{Colors.RESET}")
            return 0
        else:
            print(f"{Colors.RED}{_symbols.CROSS} Some validations failed{Colors.RESET}")
            return 1


def main():
    """Main entry point."""
    validator = FixValidator()
    validator.run_all_validations()
    return validator.print_summary()


if __name__ == "__main__":
    sys.exit(main())

