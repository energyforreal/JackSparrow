#!/usr/bin/env python3
"""
Comprehensive Error Reporting System for JackSparrow Trading Agent.

Collects and reports errors from all services, logs, and system components.
"""

import os
import sys
import json
import platform
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import defaultdict
import re


class ErrorReporter:
    """Comprehensive error reporting system."""
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialize error reporter.
        
        Args:
            project_root: Project root directory. If None, auto-detects.
        """
        if project_root is None:
            script_path = Path(__file__).resolve()
            project_root = script_path.parent.parent.parent
        
        self.project_root = project_root
        self.logs_dir = project_root / "logs"
        self.errors: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.warnings: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.summary: Dict[str, Any] = {}
    
    def scan_log_files(self) -> None:
        """Scan log files for errors and warnings."""
        if not self.logs_dir.exists():
            return
        
        error_patterns = [
            (r'ERROR|CRITICAL|FATAL', 'error'),
            (r'WARNING|WARN', 'warning'),
            (r'Exception|Traceback|Error:', 'exception'),
        ]
        
        log_files = list(self.logs_dir.glob("*.log")) + list(self.logs_dir.glob("**/*.log"))
        
        for log_file in log_files:
            service_name = log_file.stem.replace("_startup", "").replace("_error", "")
            
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    
                    for line_num, line in enumerate(lines, 1):
                        for pattern, error_type in error_patterns:
                            if re.search(pattern, line, re.IGNORECASE):
                                entry = {
                                    "file": str(log_file.relative_to(self.project_root)),
                                    "line": line_num,
                                    "message": line.strip()[:200],
                                    "timestamp": self._extract_timestamp(line),
                                }
                                
                                if error_type == 'error':
                                    self.errors[service_name].append(entry)
                                elif error_type == 'warning':
                                    self.warnings[service_name].append(entry)
                                
                                break  # Only match first pattern
            except Exception as e:
                # Skip files that can't be read
                continue
    
    def _extract_timestamp(self, line: str) -> Optional[str]:
        """Extract timestamp from log line."""
        # Try ISO format
        iso_match = re.search(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', line)
        if iso_match:
            return iso_match.group(0)
        return None
    
    def check_service_status(self) -> None:
        """Check service status from PID files and process info."""
        pid_dir = self.logs_dir
        
        services = ["backend", "agent", "frontend"]
        
        for service in services:
            pid_file = pid_dir / f"{service}.pid"
            
            if pid_file.exists():
                try:
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    
                    # Check if process is running (platform-specific)
                    if platform.system() == "Windows":
                        import subprocess
                        try:
                            result = subprocess.run(
                                ["tasklist", "/FI", f"PID eq {pid}"],
                                capture_output=True,
                                text=True
                            )
                            if str(pid) not in result.stdout:
                                self.errors[service].append({
                                    "type": "process_dead",
                                    "message": f"Process {pid} not found in task list",
                                    "pid": pid,
                                })
                        except Exception:
                            pass
                    else:
                        # Unix-like
                        if not Path(f"/proc/{pid}").exists():
                            self.errors[service].append({
                                "type": "process_dead",
                                "message": f"Process {pid} not found",
                                "pid": pid,
                            })
                except (ValueError, FileNotFoundError):
                    self.warnings[service].append({
                        "type": "pid_file_invalid",
                        "message": f"PID file exists but contains invalid data",
                    })
    
    def check_configuration_errors(self) -> None:
        """Check for configuration-related errors."""
        env_file = self.project_root / ".env"
        
        if not env_file.exists():
            self.errors["configuration"].append({
                "type": "missing_env_file",
                "message": ".env file not found",
                "file": ".env",
            })
            return
        
        # Check for common configuration issues
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # Check for placeholder values
                placeholders = [
                    ("your_secret_key_here", "JWT_SECRET_KEY"),
                    ("dev-jwt-secret", "JWT_SECRET_KEY"),
                    ("your_api_key_here", "API_KEY"),
                    ("dev-api-key", "API_KEY"),
                ]
                
                for placeholder, var_name in placeholders:
                    if placeholder in content:
                        self.warnings["configuration"].append({
                            "type": "placeholder_value",
                            "message": f"{var_name} contains placeholder value",
                            "variable": var_name,
                        })
        except Exception as e:
            self.errors["configuration"].append({
                "type": "env_read_error",
                "message": f"Failed to read .env file: {e}",
            })
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive error report.
        
        Returns:
            Dictionary containing error report
        """
        self.scan_log_files()
        self.check_service_status()
        self.check_configuration_errors()
        
        total_errors = sum(len(errors) for errors in self.errors.values())
        total_warnings = sum(len(warnings) for warnings in self.warnings.values())
        
        self.summary = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "services_with_errors": list(self.errors.keys()),
            "services_with_warnings": list(self.warnings.keys()),
        }
        
        return {
            "summary": self.summary,
            "errors": dict(self.errors),
            "warnings": dict(self.warnings),
        }
    
    def print_report(self, report: Optional[Dict[str, Any]] = None) -> None:
        """Print error report to console.
        
        Args:
            report: Error report dictionary. If None, generates new report.
        """
        if report is None:
            report = self.generate_report()
        
        is_windows = platform.system() == "Windows"
        error_symbol = "X" if is_windows else "❌"
        warning_symbol = "!" if is_windows else "⚠️"
        success_symbol = "OK" if is_windows else "✅"
        
        print(f"\n{'='*70}")
        print("Comprehensive Error Report")
        print(f"{'='*70}\n")
        
        summary = report["summary"]
        print(f"Timestamp: {summary['timestamp']}")
        print(f"Total Errors: {summary['total_errors']}")
        print(f"Total Warnings: {summary['total_warnings']}\n")
        
        if summary['total_errors'] > 0:
            print(f"{error_symbol} ERRORS BY SERVICE:\n")
            for service, errors in report["errors"].items():
                if errors:
                    print(f"  {service.upper()}: {len(errors)} error(s)")
                    for error in errors[:5]:  # Show first 5
                        msg = error.get("message", str(error))
                        print(f"    - {msg[:100]}")
                    if len(errors) > 5:
                        print(f"    ... and {len(errors) - 5} more")
                    print()
        
        if summary['total_warnings'] > 0:
            print(f"{warning_symbol} WARNINGS BY SERVICE:\n")
            for service, warnings in report["warnings"].items():
                if warnings:
                    print(f"  {service.upper()}: {len(warnings)} warning(s)")
                    for warning in warnings[:3]:  # Show first 3
                        msg = warning.get("message", str(warning))
                        print(f"    - {msg[:100]}")
                    if len(warnings) > 3:
                        print(f"    ... and {len(warnings) - 3} more")
                    print()
        
        if summary['total_errors'] == 0 and summary['total_warnings'] == 0:
            print(f"{success_symbol} No errors or warnings found!")
            print()
        elif summary['total_errors'] == 0:
            print(f"{success_symbol} No critical errors found, but please review warnings above.")
            print()
        else:
            print(f"{error_symbol} Errors detected. Please review and fix issues above.")
            print()
    
    def save_report(self, report: Optional[Dict[str, Any]] = None, output_file: Optional[Path] = None) -> Path:
        """Save error report to JSON file.
        
        Args:
            report: Error report dictionary. If None, generates new report.
            output_file: Output file path. If None, uses logs directory.
            
        Returns:
            Path to saved report file
        """
        if report is None:
            report = self.generate_report()
        
        if output_file is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_file = self.logs_dir / f"error_report_{timestamp}.json"
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)
        
        return output_file


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Comprehensive error reporting")
    parser.add_argument("--output", "-o", type=Path, help="Output JSON file path")
    parser.add_argument("--json-only", action="store_true", help="Only output JSON, no console output")
    
    args = parser.parse_args()
    
    reporter = ErrorReporter()
    report = reporter.generate_report()
    
    if not args.json_only:
        reporter.print_report(report)
    
    output_file = reporter.save_report(report, args.output)
    
    if not args.json_only:
        print(f"Report saved to: {output_file}")
    
    # Exit with error code if errors found
    if report["summary"]["total_errors"] > 0:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()

