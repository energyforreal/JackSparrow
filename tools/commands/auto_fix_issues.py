#!/usr/bin/env python3
"""
Auto-Fix Issues for JackSparrow Trading Agent

Automatically fixes common issues identified during monitoring and analysis.
"""

import os
import sys
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

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
class FixResult:
    """Result of applying a fix."""
    file_path: Path
    issue_type: str
    line_number: int
    fixed: bool
    description: str
    original_code: str
    fixed_code: str
    backup_created: bool = False


@dataclass
class AutoFixReport:
    """Report of auto-fix operations."""
    total_issues: int
    fixes_applied: int
    fixes_failed: int
    backups_created: List[Path]
    detailed_results: List[FixResult]


class AutoFixer:
    """Automatically fixes common issues in Python code."""

    def __init__(self, project_root: Path, create_backups: bool = True):
        """Initialize auto-fixer.

        Args:
            project_root: Root directory of the project
            create_backups: Whether to create backup files before fixing
        """
        self.project_root = project_root
        self.create_backups = create_backups
        self.backups_created: List[Path] = []

    def fix_missing_error_logging(self, file_path: Path, analysis_results: Dict[str, Any]) -> List[FixResult]:
        """Fix missing error logging in a file.

        Args:
            file_path: Path to the Python file to fix
            analysis_results: Results from error logging verification

        Returns:
            List of fix results
        """
        results = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            lines = content.splitlines()
            modified_lines = lines.copy()
            fixes_applied = 0

            # Parse the file to understand structure
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError:
                return [FixResult(
                    file_path=file_path,
                    issue_type="syntax_error",
                    line_number=1,
                    fixed=False,
                    description="Cannot fix file with syntax errors",
                    original_code="",
                    fixed_code=""
                )]

            # Find try/except blocks and fix missing logging
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        # Check if this handler needs logging
                        handler_lines = content.splitlines()[handler.lineno - 1:handler.end_lineno]
                        handler_code = '\n'.join(handler_lines)

                        # Skip if already has logging
                        if self._has_logging(handler_code):
                            continue

                        # Generate fix
                        fix_result = self._add_error_logging(handler, modified_lines, file_path)
                        if fix_result:
                            results.append(fix_result)
                            fixes_applied += 1

            # Apply all fixes to the file
            if fixes_applied > 0:
                self._apply_fixes(file_path, modified_lines)

        except Exception as e:
            results.append(FixResult(
                file_path=file_path,
                issue_type="fix_error",
                line_number=0,
                fixed=False,
                description=f"Failed to apply fixes: {e}",
                original_code="",
                fixed_code=""
            ))

        return results

    def fix_bare_except_clauses(self, file_path: Path) -> List[FixResult]:
        """Fix bare except clauses by making them more specific.

        Args:
            file_path: Path to the Python file to fix

        Returns:
            List of fix results
        """
        results = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            lines = content.splitlines()
            modified_lines = lines.copy()

            # Use regex to find bare except clauses
            bare_except_pattern = r'^\s*except\s*:\s*$'

            for i, line in enumerate(lines, 1):
                if re.match(bare_except_pattern, line.strip()):
                    # Make the except clause more specific
                    original = line
                    fixed = line.replace('except:', 'except Exception as e:')

                    modified_lines[i-1] = fixed

                    results.append(FixResult(
                        file_path=file_path,
                        issue_type="bare_except",
                        line_number=i,
                        fixed=True,
                        description="Replaced bare 'except:' with 'except Exception as e:'",
                        original_code=original,
                        fixed_code=fixed
                    ))

            # Apply fixes if any were made
            if results:
                self._apply_fixes(file_path, modified_lines)

        except Exception as e:
            results.append(FixResult(
                file_path=file_path,
                issue_type="fix_error",
                line_number=0,
                fixed=False,
                description=f"Failed to fix bare except clauses: {e}",
                original_code="",
                fixed_code=""
            ))

        return results

    def _has_logging(self, code: str) -> bool:
        """Check if code contains logging calls."""
        logging_patterns = [
            r'\blogger\.\w+\s*\(',
            r'\blog_error_with_context\s*\(',
            r'\blog_exception\s*\(',
            r'\blogging\.\w+\s*\(',
            r'\bstructlog\.\w+\s*\('
        ]

        for pattern in logging_patterns:
            if re.search(pattern, code):
                return True

        return False

    def _add_error_logging(self, handler: ast.ExceptHandler, lines: List[str], file_path: Path) -> Optional[FixResult]:
        """Add error logging to an exception handler."""
        # Get the exception variable name
        exc_name = 'e'  # Default
        if handler.name:
            exc_name = handler.name

        # Find the indentation level
        handler_line = lines[handler.lineno - 1]
        indent_match = re.match(r'^(\s*)', handler_line)
        indent = indent_match.group(1) if indent_match else ""

        # Determine component name from file path
        rel_path = file_path.relative_to(self.project_root)
        component = str(rel_path).replace('/', '.').replace('\\', '.').replace('.py', '')

        # Generate logging call
        if 'agent' in str(rel_path):
            # Agent logging
            log_call = f'{indent}    log_error_with_context('
            log_call += f'\n{indent}        "exception_occurred",'
            log_call += f'\n{indent}        error={exc_name},'
            log_call += f'\n{indent}        component="{component}",'
            log_call += f'\n{indent}        request_id=getattr(context_manager, "current_request_id", None)'
            log_call += f'\n{indent}    )'
        else:
            # Backend logging
            log_call = f'{indent}    log_error_with_context('
            log_call += f'\n{indent}        "exception_occurred",'
            log_call += f'\n{indent}        error={exc_name},'
            log_call += f'\n{indent}        component="{component}"'
            log_call += f'\n{indent}    )'

        # Find where to insert the logging call
        # Insert at the beginning of the except block
        insert_line = handler.lineno

        # Skip the except line itself
        if insert_line < len(lines):
            insert_line += 1

        # Insert the logging call
        original_lines = lines.copy()
        lines.insert(insert_line, log_call)

        # Create result
        return FixResult(
            file_path=file_path,
            issue_type="missing_log",
            line_number=handler.lineno,
            fixed=True,
            description="Added structured error logging to exception handler",
            original_code='\n'.join(original_lines[handler.lineno-1:handler.end_lineno]),
            fixed_code='\n'.join(lines[handler.lineno-1:handler.end_lineno + len(log_call.split('\n')) - 1])
        )

    def _apply_fixes(self, file_path: Path, modified_lines: List[str]):
        """Apply fixes to a file."""
        if self.create_backups:
            backup_path = file_path.with_suffix('.bak')
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    original_content = f.read()

                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)

                self.backups_created.append(backup_path)
            except Exception as e:
                print(f"{Colors.YELLOW}⚠️  Failed to create backup for {file_path}: {e}{Colors.RESET}", file=sys.stderr)

        # Write the modified content
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(modified_lines))
        except Exception as e:
            raise Exception(f"Failed to write fixed file {file_path}: {e}")

    def fix_configuration_issues(self) -> List[FixResult]:
        """Fix common configuration issues."""
        results = []

        # Check for missing .env file
        env_file = self.project_root / ".env"
        if not env_file.exists():
            try:
                # Create a basic .env file
                env_content = """# JackSparrow Trading Agent Configuration
# Copy this file and update with your actual values

# Database
DATABASE_URL=postgresql://jacksparrow:jacksparrow@localhost:5432/trading_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# Delta Exchange API (Paper Trading)
DELTA_EXCHANGE_API_KEY=your_api_key_here
DELTA_EXCHANGE_API_SECRET=your_api_secret_here
DELTA_EXCHANGE_BASE_URL=https://api.india.delta.exchange

# JWT Security
JWT_SECRET_KEY=your_jwt_secret_key_here

# API Key
API_KEY=your_api_key_here

# Trading Mode (PAPER_TRADING_MODE=true for safe paper trading)
PAPER_TRADING_MODE=true
TRADING_MODE=live

# Logging
AGENT_LOG_LEVEL=INFO
BACKEND_LOG_LEVEL=INFO

# Feature Server
FEATURE_SERVER_PORT=8001

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_BACKEND_API_KEY=your_api_key_here
"""

                with open(env_file, 'w', encoding='utf-8') as f:
                    f.write(env_content)

                results.append(FixResult(
                    file_path=env_file,
                    issue_type="missing_env_file",
                    line_number=1,
                    fixed=True,
                    description="Created basic .env configuration file",
                    original_code="",
                    fixed_code="Configuration file created"
                ))

            except Exception as e:
                results.append(FixResult(
                    file_path=env_file,
                    issue_type="missing_env_file",
                    line_number=1,
                    fixed=False,
                    description=f"Failed to create .env file: {e}",
                    original_code="",
                    fixed_code=""
                ))

        return results

    def run_auto_fix(self, issues_report: Dict[str, Any]) -> AutoFixReport:
        """Run comprehensive auto-fix on issues report.

        Args:
            issues_report: Report from error logging verification

        Returns:
            Comprehensive auto-fix report
        """
        print(f"{Colors.BLUE}🔧 Running auto-fix for identified issues...{Colors.RESET}")

        total_issues = 0
        fixes_applied = 0
        fixes_failed = 0
        detailed_results = []

        # Fix configuration issues first
        config_results = self.fix_configuration_issues()
        detailed_results.extend(config_results)
        fixes_applied += sum(1 for r in config_results if r.fixed)

        # Fix issues in individual files
        if "files_with_issues" in issues_report:
            for file_info in issues_report["files_with_issues"]:
                file_path = self.project_root / file_info["file_path"]

                if not file_path.exists():
                    continue

                file_issues = file_info["issues"]
                total_issues += len(file_issues)

                # Fix missing error logging
                missing_log_issues = [i for i in file_issues if i["issue_type"] == "missing_log"]
                if missing_log_issues:
                    try:
                        logging_results = self.fix_missing_error_logging(file_path, file_info)
                        detailed_results.extend(logging_results)
                        fixes_applied += sum(1 for r in logging_results if r.fixed)
                        fixes_failed += sum(1 for r in logging_results if not r.fixed)
                    except Exception as e:
                        detailed_results.append(FixResult(
                            file_path=file_path,
                            issue_type="fix_error",
                            line_number=0,
                            fixed=False,
                            description=f"Failed to fix missing logging: {e}",
                            original_code="",
                            fixed_code=""
                        ))
                        fixes_failed += 1

                # Fix bare except clauses
                bare_except_issues = [i for i in file_issues if i["issue_type"] == "bare_except"]
                if bare_except_issues:
                    try:
                        bare_results = self.fix_bare_except_clauses(file_path)
                        detailed_results.extend(bare_results)
                        fixes_applied += sum(1 for r in bare_results if r.fixed)
                        fixes_failed += sum(1 for r in bare_results if not r.fixed)
                    except Exception as e:
                        detailed_results.append(FixResult(
                            file_path=file_path,
                            issue_type="fix_error",
                            line_number=0,
                            fixed=False,
                            description=f"Failed to fix bare except clauses: {e}",
                            original_code="",
                            fixed_code=""
                        ))
                        fixes_failed += 1

        return AutoFixReport(
            total_issues=total_issues,
            fixes_applied=fixes_applied,
            fixes_failed=fixes_failed,
            backups_created=self.backups_created,
            detailed_results=detailed_results
        )

    def print_report(self, report: AutoFixReport):
        """Print comprehensive auto-fix report."""
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}🔧 AUTO-FIX REPORT{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")

        print(f"\n{Colors.BOLD}📊 Summary:{Colors.RESET}")
        print(f"  Total Issues Found: {Colors.BLUE}{report.total_issues:,}{Colors.RESET}")
        print(f"  Fixes Applied: {Colors.GREEN}{report.fixes_applied:,}{Colors.RESET}")
        print(f"  Fixes Failed: {Colors.RED}{report.fixes_failed:,}{Colors.RESET}")

        success_rate = (report.fixes_applied / max(report.total_issues, 1)) * 100
        if success_rate >= 90:
            rate_color = Colors.GREEN
        elif success_rate >= 75:
            rate_color = Colors.YELLOW
        else:
            rate_color = Colors.RED

        print(f"  Success Rate: {rate_color}{success_rate:.1f}%{Colors.RESET}")

        if report.backups_created:
            print(f"\n{Colors.BOLD}💾 Backups Created:{Colors.RESET}")
            for backup in report.backups_created:
                rel_path = backup.relative_to(self.project_root)
                print(f"  {Colors.BLUE}• {rel_path}{Colors.RESET}")

        # Group results by file
        results_by_file = {}
        for result in report.detailed_results:
            file_path = str(result.file_path.relative_to(self.project_root))
            if file_path not in results_by_file:
                results_by_file[file_path] = []
            results_by_file[file_path].append(result)

        if results_by_file:
            print(f"\n{Colors.BOLD}📋 Detailed Results by File:{Colors.RESET}")
            for file_path, file_results in sorted(results_by_file.items()):
                successful_fixes = sum(1 for r in file_results if r.fixed)
                failed_fixes = sum(1 for r in file_results if not r.fixed)

                print(f"\n  {Colors.BOLD}{file_path}{Colors.RESET}")
                print(f"    Fixed: {Colors.GREEN}{successful_fixes}{Colors.RESET} | Failed: {Colors.RED}{failed_fixes}{Colors.RESET}")

                # Show details for first few fixes
                for result in file_results[:3]:
                    status = f"{Colors.GREEN}✓{Colors.RESET}" if result.fixed else f"{Colors.RED}✗{Colors.RESET}"
                    print(f"    {status} {result.description}")

                if len(file_results) > 3:
                    print(f"    {Colors.DIM}... and {len(file_results) - 3} more{Colors.RESET}")

        print(f"\n{Colors.BOLD}✅ Auto-fix operations completed{Colors.RESET}")

        if report.fixes_applied > 0:
            print(f"\n{Colors.YELLOW}⚠️  Remember to review and test the changes before deploying!{Colors.RESET}")


def main():
    """Main entry point."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Auto-fix common issues in JackSparrow")
    parser.add_argument("--project-root", type=Path, default=project_root,
                       help="Project root directory")
    parser.add_argument("--issues-report", type=Path,
                       help="JSON file with issues report from verify_error_logging.py")
    parser.add_argument("--no-backups", action="store_true",
                       help="Don't create backup files before fixing")
    parser.add_argument("--output-json", type=Path,
                       help="Save fix report as JSON to file")
    parser.add_argument("--quiet", action="store_true",
                       help="Suppress console output")

    args = parser.parse_args()

    fixer = AutoFixer(args.project_root, create_backups=not args.no_backups)

    try:
        # Load issues report if provided
        issues_report = {}
        if args.issues_report:
            if args.issues_report.exists():
                with open(args.issues_report, 'r', encoding='utf-8') as f:
                    issues_report = json.load(f)
            else:
                print(f"{Colors.RED}❌ Issues report file not found: {args.issues_report}{Colors.RESET}")
                sys.exit(1)
        else:
            # Run verification first to get issues
            print(f"{Colors.BLUE}🔍 Running error logging verification first...{Colors.RESET}")
            from tools.commands.verify_error_logging import ErrorLoggingVerifier

            verifier = ErrorLoggingVerifier(args.project_root)
            coverage_report = verifier.scan_project()

            # Convert coverage report to issues format
            issues_report = {
                "total_files": coverage_report.total_files,
                "issues_by_type": coverage_report.issues_by_type,
                "files_with_issues": [
                    {
                        "file_path": str(analysis.file_path.relative_to(args.project_root)),
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
                    for analysis in coverage_report.files_with_issues
                ]
            }

        # Run auto-fix
        fix_report = fixer.run_auto_fix(issues_report)

        if not args.quiet:
            fixer.print_report(fix_report)

        if args.output_json:
            # Convert report to JSON-serializable format
            json_report = {
                "total_issues": fix_report.total_issues,
                "fixes_applied": fix_report.fixes_applied,
                "fixes_failed": fix_report.fixes_failed,
                "backups_created": [str(b.relative_to(args.project_root)) for b in fix_report.backups_created],
                "detailed_results": [
                    {
                        "file_path": str(result.file_path.relative_to(args.project_root)),
                        "issue_type": result.issue_type,
                        "line_number": result.line_number,
                        "fixed": result.fixed,
                        "description": result.description,
                        "backup_created": result.backup_created
                    }
                    for result in fix_report.detailed_results
                ]
            }

            with open(args.output_json, 'w', encoding='utf-8') as f:
                json.dump(json_report, f, indent=2, ensure_ascii=False)

            print(f"\n{Colors.GREEN}✅ Fix report saved to {args.output_json}{Colors.RESET}")

    except Exception as e:
        print(f"{Colors.RED}❌ Auto-fix failed: {e}{Colors.RESET}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()