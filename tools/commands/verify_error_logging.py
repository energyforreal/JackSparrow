#!/usr/bin/env python3
"""
Error Logging Coverage Verifier for JackSparrow Trading Agent

Scans Python files to verify error logging coverage and identify missing error handling.
"""

import os
import sys
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# ANSI color codes
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


@dataclass
class ErrorHandlingIssue:
    """Issue with error handling/logging."""
    file_path: Path
    line_number: int
    issue_type: str  # "missing_log", "bare_except", "untyped_exception", "missing_context"
    severity: str  # "high", "medium", "low"
    description: str
    code_snippet: str
    suggestion: str


@dataclass
class FileAnalysis:
    """Analysis results for a single file."""
    file_path: Path
    total_lines: int
    try_blocks: int
    except_blocks: int
    logged_exceptions: int
    bare_excepts: int
    issues: List[ErrorHandlingIssue] = field(default_factory=list)


@dataclass
class CoverageReport:
    """Overall coverage report."""
    total_files: int
    total_lines: int
    total_try_blocks: int
    total_logged_exceptions: int
    total_bare_excepts: int
    coverage_percentage: float
    issues_by_severity: Dict[str, int]
    issues_by_type: Dict[str, int]
    files_with_issues: List[FileAnalysis]
    critical_files: List[Path]


class ErrorLoggingVerifier:
    """Verifies error logging coverage in Python files."""

    def __init__(self, project_root: Path):
        """Initialize verifier.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.python_files: List[Path] = []
        self.known_logging_functions = {
            "logger.error", "logger.exception", "logger.critical",
            "log_error_with_context", "log_exception", "log_warning_with_context",
            "logging.error", "logging.exception", "logging.critical"
        }

    def scan_project(self, directories: List[str] = None) -> CoverageReport:
        """Scan project for error logging coverage.

        Args:
            directories: List of directories to scan. Defaults to ["agent", "backend"]

        Returns:
            Comprehensive coverage report
        """
        if directories is None:
            directories = ["agent", "backend"]

        print(f"{Colors.BLUE}[INFO] Scanning Python files for error logging coverage...{Colors.RESET}")

        # Find all Python files
        for directory in directories:
            dir_path = self.project_root / directory
            if dir_path.exists():
                self.python_files.extend(dir_path.rglob("*.py"))

        print(f"{Colors.BLUE}[INFO] Found {len(self.python_files)} Python files to analyze{Colors.RESET}")

        # Analyze each file
        file_analyses = []
        for file_path in self.python_files:
            try:
                analysis = self._analyze_file(file_path)
                file_analyses.append(analysis)
            except Exception as e:
                print(f"{Colors.YELLOW}[WARN] Failed to analyze {file_path}: {e}{Colors.RESET}", file=sys.stderr)

        # Generate overall report
        report = self._generate_report(file_analyses)
        return report

    def _analyze_file(self, file_path: Path) -> FileAnalysis:
        """Analyze a single Python file for error handling patterns."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        lines = content.splitlines()
        total_lines = len(lines)

        # Parse AST to find try/except blocks
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            # If file has syntax errors, we can't analyze it properly
            return FileAnalysis(
                file_path=file_path,
                total_lines=total_lines,
                try_blocks=0,
                except_blocks=0,
                logged_exceptions=0,
                bare_excepts=0,
                issues=[ErrorHandlingIssue(
                    file_path=file_path,
                    line_number=1,
                    issue_type="syntax_error",
                    severity="high",
                    description="File contains syntax errors preventing analysis",
                    code_snippet="",
                    suggestion="Fix syntax errors before analysis"
                )]
            )

        # Find all try/except blocks
        try_blocks = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                try_blocks.append(node)

        issues = []

        try_count = len(try_blocks)
        except_count = 0
        logged_exceptions = 0
        bare_excepts = 0

        for try_block in try_blocks:
            except_count += len(try_block.handlers)

            # Analyze each except handler
            for handler in try_block.handlers:
                except_count += 1

                # Check for bare except
                if handler.type is None:
                    bare_excepts += 1
                    issues.append(ErrorHandlingIssue(
                        file_path=file_path,
                        line_number=handler.lineno,
                        issue_type="bare_except",
                        severity="high",
                        description="Bare 'except:' clause catches all exceptions",
                        code_snippet=self._get_code_snippet(lines, handler.lineno, 2),
                        suggestion="Specify exception types to catch, e.g., 'except (ValueError, TypeError):'"
                    ))

                # Check for logging in the except block
                has_logging = self._check_exception_logging(handler, content)

                if not has_logging:
                    issues.append(ErrorHandlingIssue(
                        file_path=file_path,
                        line_number=handler.lineno,
                        issue_type="missing_log",
                        severity="medium",
                        description="Exception not logged with structured logging",
                        code_snippet=self._get_code_snippet(lines, handler.lineno, 4),
                        suggestion="Add structured error logging: logger.error('error_message', error=exc, component='component_name')"
                    ))
                else:
                    logged_exceptions += 1

        return FileAnalysis(
            file_path=file_path,
            total_lines=total_lines,
            try_blocks=try_count,
            except_blocks=except_count,
            logged_exceptions=logged_exceptions,
            bare_excepts=bare_excepts,
            issues=issues
        )

    def _check_exception_logging(self, handler: ast.ExceptHandler, content: str) -> bool:
        """Check if an exception handler contains proper logging."""
        # Get the source lines for this handler
        handler_lines = content.splitlines()[handler.lineno - 1:handler.end_lineno]

        # Look for logging function calls
        handler_code = '\n'.join(handler_lines)

        # Check for known logging functions
        for log_func in self.known_logging_functions:
            if log_func in handler_code:
                return True

        # Check for logger calls (more flexible pattern)
        if re.search(r'\b\w*logger?\.\w*\s*\(', handler_code):
            return True

        # Check for structlog calls
        if 'structlog' in handler_code or 'bind_contextvars' in handler_code:
            return True

        # Check for error context functions
        if any(func in handler_code for func in ['log_error_with_context', 'log_exception']):
            return True

        return False

    def _get_code_snippet(self, lines: List[str], line_number: int, context_lines: int = 2) -> str:
        """Get code snippet around a line number."""
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        snippet_lines = lines[start:end]

        # Add line numbers
        numbered_lines = []
        for i, line in enumerate(snippet_lines, start + 1):
            marker = ">>>" if i == line_number else "   "
            numbered_lines.append(f"{marker} {i:3d}: {line}")

        return '\n'.join(numbered_lines)

    def _generate_report(self, file_analyses: List[FileAnalysis]) -> CoverageReport:
        """Generate overall coverage report."""
        total_files = len(file_analyses)
        total_lines = sum(analysis.total_lines for analysis in file_analyses)
        total_try_blocks = sum(analysis.try_blocks for analysis in file_analyses)
        total_logged_exceptions = sum(analysis.logged_exceptions for analysis in file_analyses)
        total_bare_excepts = sum(analysis.bare_excepts for analysis in file_analyses)

        # Calculate coverage
        if total_try_blocks > 0:
            coverage_percentage = (total_logged_exceptions / total_try_blocks) * 100
        else:
            coverage_percentage = 100.0

        # Collect all issues
        all_issues = []
        for analysis in file_analyses:
            all_issues.extend(analysis.issues)

        # Group issues by severity and type
        issues_by_severity = defaultdict(int)
        issues_by_type = defaultdict(int)

        for issue in all_issues:
            issues_by_severity[issue.severity] += 1
            issues_by_type[issue.issue_type] += 1

        # Files with issues
        files_with_issues = [analysis for analysis in file_analyses if analysis.issues]

        # Critical files (high severity issues)
        critical_files = []
        for analysis in file_analyses:
            if any(issue.severity == "high" for issue in analysis.issues):
                critical_files.append(analysis.file_path)

        return CoverageReport(
            total_files=total_files,
            total_lines=total_lines,
            total_try_blocks=total_try_blocks,
            total_logged_exceptions=total_logged_exceptions,
            total_bare_excepts=total_bare_excepts,
            coverage_percentage=coverage_percentage,
            issues_by_severity=dict(issues_by_severity),
            issues_by_type=dict(issues_by_type),
            files_with_issues=files_with_issues,
            critical_files=critical_files
        )

    def print_report(self, report: CoverageReport):
        """Print comprehensive coverage report."""
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}ERROR LOGGING COVERAGE REPORT{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")

        print(f"\n{Colors.BOLD}[SUMMARY] Coverage Summary:{Colors.RESET}")
        print(f"  Files Analyzed: {Colors.BLUE}{report.total_files:,}{Colors.RESET}")
        print(f"  Total Lines: {Colors.BLUE}{report.total_lines:,}{Colors.RESET}")
        print(f"  Try/Except Blocks: {Colors.BLUE}{report.total_try_blocks:,}{Colors.RESET}")
        print(f"  Logged Exceptions: {Colors.GREEN}{report.total_logged_exceptions:,}{Colors.RESET}")
        print(f"  Bare Except Clauses: {Colors.RED}{report.total_bare_excepts:,}{Colors.RESET}")

        # Coverage score
        if report.coverage_percentage >= 90:
            coverage_color = Colors.GREEN
            rating = "EXCELLENT"
        elif report.coverage_percentage >= 75:
            coverage_color = Colors.YELLOW
            rating = "GOOD"
        elif report.coverage_percentage >= 50:
            coverage_color = Colors.BLUE
            rating = "FAIR"
        else:
            coverage_color = Colors.RED
            rating = "NEEDS IMPROVEMENT"

        print(f"  Coverage: {coverage_color}{report.coverage_percentage:.1f}% ({rating}){Colors.RESET}")

        if report.issues_by_severity:
            print(f"\n{Colors.BOLD}[ISSUES] Issues by Severity:{Colors.RESET}")
            severity_colors = {"high": Colors.RED, "medium": Colors.YELLOW, "low": Colors.BLUE}
            for severity, count in sorted(report.issues_by_severity.items(), key=lambda x: ["high", "medium", "low"].index(x[0])):
                color = severity_colors.get(severity, Colors.RESET)
                print(f"  {severity.capitalize()}: {color}{count}{Colors.RESET}")

        if report.issues_by_type:
            print(f"\n{Colors.BOLD}[TYPES] Issues by Type:{Colors.RESET}")
            type_descriptions = {
                "missing_log": "Missing error logging",
                "bare_except": "Bare except clauses",
                "untyped_exception": "Untyped exception handling",
                "missing_context": "Missing error context",
                "syntax_error": "Syntax errors"
            }
            for issue_type, count in sorted(report.issues_by_type.items(), key=lambda x: x[1], reverse=True):
                description = type_descriptions.get(issue_type, issue_type)
                print(f"  {description}: {Colors.RED}{count}{Colors.RESET}")

        if report.critical_files:
            print(f"\n{Colors.BOLD}[CRITICAL] Critical Files (High Severity Issues):{Colors.RESET}")
            for file_path in sorted(report.critical_files)[:10]:  # Show top 10
                rel_path = file_path.relative_to(self.project_root)
                print(f"  {Colors.RED}- {rel_path}{Colors.RESET}")
            if len(report.critical_files) > 10:
                print(f"  {Colors.DIM}... and {len(report.critical_files) - 10} more{Colors.RESET}")

        # Show detailed issues for files with most problems
        if report.files_with_issues:
            print(f"\n{Colors.BOLD}[FILES] Files with Most Issues:{Colors.RESET}")
            # Sort by number of issues
            sorted_files = sorted(report.files_with_issues,
                                key=lambda x: len(x.issues), reverse=True)[:5]

            for analysis in sorted_files:
                rel_path = analysis.file_path.relative_to(self.project_root)
                issue_count = len(analysis.issues)
                print(f"\n  {Colors.BOLD}{rel_path}{Colors.RESET} ({issue_count} issues):")

                # Group issues by type for this file
                file_issue_types = defaultdict(int)
                for issue in analysis.issues:
                    file_issue_types[issue.issue_type] += 1

                for issue_type, count in file_issue_types.items():
                    print(f"    {issue_type}: {Colors.RED}{count}{Colors.RESET}")

                # Show first high-severity issue as example
                high_severity = [i for i in analysis.issues if i.severity == "high"]
                if high_severity:
                    issue = high_severity[0]
                    print(f"    {Colors.DIM}Example: Line {issue.line_number} - {issue.description}{Colors.RESET}")

        # Recommendations
        print(f"\n{Colors.BOLD}[RECOMMENDATIONS] Recommendations:{Colors.RESET}")

        if report.coverage_percentage < 75:
            print(f"  {Colors.YELLOW}- Improve error logging coverage - aim for 90%+{Colors.RESET}")
        if report.total_bare_excepts > 0:
            print(f"  {Colors.YELLOW}- Replace bare 'except:' clauses with specific exception types{Colors.RESET}")
        if report.issues_by_type.get("missing_log", 0) > 0:
            print(f"  {Colors.YELLOW}- Add structured error logging to unhandled exceptions{Colors.RESET}")

        if report.coverage_percentage >= 90 and report.total_bare_excepts == 0:
            print(f"  {Colors.GREEN}- Error logging coverage is excellent!{Colors.RESET}")

        print(f"\n{Colors.BOLD}[COMPLETE] Analysis Complete{Colors.RESET}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Verify error logging coverage in JackSparrow")
    parser.add_argument("--project-root", type=Path, default=project_root,
                       help="Project root directory")
    parser.add_argument("--directories", nargs="+", default=["agent", "backend"],
                       help="Directories to scan (default: agent backend)")
    parser.add_argument("--output-json", type=Path,
                       help="Save report as JSON to file")
    parser.add_argument("--quiet", action="store_true",
                       help="Suppress console output")

    args = parser.parse_args()

    verifier = ErrorLoggingVerifier(args.project_root)

    try:
        report = verifier.scan_project(args.directories)

        if not args.quiet:
            verifier.print_report(report)

        if args.output_json:
            # Convert report to JSON-serializable format
            json_report = {
                "total_files": report.total_files,
                "total_lines": report.total_lines,
                "total_try_blocks": report.total_try_blocks,
                "total_logged_exceptions": report.total_logged_exceptions,
                "total_bare_excepts": report.total_bare_excepts,
                "coverage_percentage": report.coverage_percentage,
                "issues_by_severity": report.issues_by_severity,
                "issues_by_type": report.issues_by_type,
                "files_with_issues": [
                    {
                        "file_path": str(analysis.file_path.relative_to(args.project_root)),
                        "total_lines": analysis.total_lines,
                        "try_blocks": analysis.try_blocks,
                        "except_blocks": analysis.except_blocks,
                        "logged_exceptions": analysis.logged_exceptions,
                        "bare_excepts": analysis.bare_excepts,
                        "issues": [
                            {
                                "line_number": issue.line_number,
                                "issue_type": issue.issue_type,
                                "severity": issue.severity,
                                "description": issue.description,
                                "suggestion": issue.suggestion
                            }
                            for issue in analysis.issues
                        ]
                    }
                    for analysis in report.files_with_issues
                ],
                "critical_files": [str(f.relative_to(args.project_root)) for f in report.critical_files]
            }

            with open(args.output_json, 'w', encoding='utf-8') as f:
                import json
                json.dump(json_report, f, indent=2, ensure_ascii=False)

            print(f"\n{Colors.GREEN}[OK] Report saved to {args.output_json}{Colors.RESET}")

    except Exception as e:
        print(f"{Colors.RED}[ERROR] Error logging verification failed: {e}{Colors.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()