"""
Code Quality Audit Checks

This module contains all code quality audit checks for the JackSparrow project.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_python_formatting() -> AuditResult:
    """Check Python code formatting using black."""
    try:
        # Check if black is available
        result = subprocess.run(
            [sys.executable, "-m", "black", "--check", "--diff", "backend", "agent", "scripts"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60
        )

        if result.returncode == 0:
            return AuditResult(
                check_name="python_formatting",
                category="code_quality",
                severity="medium",
                status="pass",
                message="All Python code is properly formatted with black",
                details="Black formatting check passed for backend/, agent/, and scripts/ directories"
            )
        else:
            # Extract number of files that need formatting
            diff_lines = result.stdout.split('\n')
            files_needing_format = [line for line in diff_lines if line.startswith('would reformat ')]

            return AuditResult(
                check_name="python_formatting",
                category="code_quality",
                severity="medium",
                status="fail",
                message=f"{len(files_needing_format)} Python files need formatting",
                details=f"Black check failed. Run 'black backend agent scripts' to fix.\n\nFiles needing formatting:\n" + '\n'.join(files_needing_format[:10]),
                recommendations=[
                    "Run 'black backend agent scripts' to auto-format Python code",
                    "Consider adding pre-commit hooks to prevent formatting issues",
                    "Review .pre-commit-config.yaml for formatting automation"
                ]
            )

    except subprocess.TimeoutExpired:
        return AuditResult(
            check_name="python_formatting",
            category="code_quality",
            severity="medium",
            status="warning",
            message="Python formatting check timed out",
            details="The black formatting check took too long to complete",
            recommendations=["Consider running black on individual directories", "Check for large files that may be causing timeouts"]
        )
    except FileNotFoundError:
        return AuditResult(
            check_name="python_formatting",
            category="code_quality",
            severity="medium",
            status="warning",
            message="Black not installed - cannot check Python formatting",
            details="The 'black' code formatter is not installed",
            recommendations=["Install black: pip install black", "Add black to requirements-dev.txt"]
        )
    except Exception as e:
        return AuditResult(
            check_name="python_formatting",
            category="code_quality",
            severity="medium",
            status="error",
            message=f"Python formatting check failed: {str(e)}",
            details=f"Unexpected error during black check: {str(e)}"
        )


def check_python_linting() -> AuditResult:
    """Check Python code linting using ruff."""
    try:
        # Check if ruff is available
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "backend", "agent", "scripts"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=120
        )

        if result.returncode == 0:
            return AuditResult(
                check_name="python_linting",
                category="code_quality",
                severity="medium",
                status="pass",
                message="All Python code passes ruff linting checks",
                details="Ruff linting check passed for backend/, agent/, and scripts/ directories"
            )
        else:
            # Parse ruff output to get error counts
            lines = result.stdout.split('\n')
            error_lines = [line for line in lines if ': ' in line and not line.startswith(' ')]
            error_count = len(error_lines)

            # Categorize errors
            error_types = {}
            for line in error_lines[:50]:  # Limit to first 50 for readability
                if ': ' in line:
                    parts = line.split(': ')
                    if len(parts) >= 2:
                        error_code = parts[1].split(' ')[0] if ' ' in parts[1] else 'unknown'
                        error_types[error_code] = error_types.get(error_code, 0) + 1

            error_summary = "\n".join([f"- {code}: {count}" for code, count in error_types.items()])

            return AuditResult(
                check_name="python_linting",
                category="code_quality",
                severity="medium",
                status="fail",
                message=f"Found {error_count} Python linting issues",
                details=f"Ruff found {error_count} issues:\n{error_summary}\n\nFirst 20 issues:\n" + '\n'.join(error_lines[:20]),
                recommendations=[
                    "Run 'ruff check backend agent scripts --fix' to auto-fix issues",
                    "Run 'ruff check backend agent scripts' for detailed output",
                    "Review ruff error codes and fix manually if needed",
                    "Consider adding ruff to pre-commit hooks"
                ]
            )

    except subprocess.TimeoutExpired:
        return AuditResult(
            check_name="python_linting",
            category="code_quality",
            severity="medium",
            status="warning",
            message="Python linting check timed out",
            details="The ruff linting check took too long to complete",
            recommendations=["Run ruff on individual directories", "Check for large files causing timeouts"]
        )
    except FileNotFoundError:
        return AuditResult(
            check_name="python_linting",
            category="code_quality",
            severity="medium",
            status="warning",
            message="Ruff not installed - cannot check Python linting",
            details="The 'ruff' linter is not installed",
            recommendations=["Install ruff: pip install ruff", "Add ruff to requirements-dev.txt"]
        )
    except Exception as e:
        return AuditResult(
            check_name="python_linting",
            category="code_quality",
            severity="medium",
            status="error",
            message=f"Python linting check failed: {str(e)}",
            details=f"Unexpected error during ruff check: {str(e)}"
        )


def check_typescript_quality() -> AuditResult:
    """Check TypeScript/React code quality."""
    frontend_dir = project_root / "frontend"

    if not frontend_dir.exists():
        return AuditResult(
            check_name="typescript_quality",
            category="code_quality",
            severity="low",
            status="skip",
            message="Frontend directory not found - skipping TypeScript checks"
        )

    try:
        # Check if we're in a Node.js project
        package_json = frontend_dir / "package.json"
        if not package_json.exists():
            return AuditResult(
                check_name="typescript_quality",
                category="code_quality",
                severity="medium",
                status="warning",
                message="package.json not found in frontend directory",
                recommendations=["Ensure frontend is properly initialized"]
            )

        # Check TypeScript compilation
        result = subprocess.run(
            ["npm", "run", "type-check"],
            capture_output=True,
            text=True,
            cwd=frontend_dir,
            timeout=60
        )

        type_check_passed = result.returncode == 0

        # Check linting if available
        lint_result = subprocess.run(
            ["npm", "run", "lint"],
            capture_output=True,
            text=True,
            cwd=frontend_dir,
            timeout=60
        )

        lint_passed = lint_result.returncode == 0

        if type_check_passed and lint_passed:
            return AuditResult(
                check_name="typescript_quality",
                category="code_quality",
                severity="medium",
                status="pass",
                message="TypeScript code passes type checking and linting",
                details="Both TypeScript compilation and ESLint checks passed"
            )
        else:
            issues = []
            if not type_check_passed:
                issues.append("TypeScript compilation failed")
            if not lint_passed:
                issues.append("ESLint failed")

            details = ""
            if result.stdout or result.stderr:
                details += f"TypeScript output:\n{result.stdout}\n{result.stderr}\n"
            if lint_result.stdout or lint_result.stderr:
                details += f"ESLint output:\n{lint_result.stdout}\n{lint_result.stderr}"

            return AuditResult(
                check_name="typescript_quality",
                category="code_quality",
                severity="medium",
                status="fail",
                message=f"TypeScript/React quality issues found: {', '.join(issues)}",
                details=details.strip(),
                recommendations=[
                    "Run 'npm run type-check' to see TypeScript errors",
                    "Run 'npm run lint' to see linting issues",
                    "Fix TypeScript compilation errors first",
                    "Address ESLint warnings and errors"
                ]
            )

    except subprocess.TimeoutExpired:
        return AuditResult(
            check_name="typescript_quality",
            category="code_quality",
            severity="medium",
            status="warning",
            message="TypeScript quality check timed out",
            recommendations=["Run TypeScript checks manually", "Check for large files causing timeouts"]
        )
    except FileNotFoundError:
        return AuditResult(
            check_name="typescript_quality",
            category="code_quality",
            severity="medium",
            status="warning",
            message="npm not found - cannot check TypeScript quality",
            recommendations=["Ensure Node.js and npm are installed", "Check PATH environment variable"]
        )
    except Exception as e:
        return AuditResult(
            check_name="typescript_quality",
            category="code_quality",
            severity="medium",
            status="error",
            message=f"TypeScript quality check failed: {str(e)}",
            details=f"Unexpected error: {str(e)}"
        )


def check_code_complexity() -> AuditResult:
    """Check code complexity using radon."""
    try:
        # Check if radon is available
        result = subprocess.run(
            [sys.executable, "-m", "radon", "cc", "--min", "C", "--max", "F", "--show-complexity", "--average", "--total-average", "backend", "agent"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60
        )

        if result.returncode == 0:
            # Parse radon output to check for high complexity
            lines = result.stdout.split('\n')

            # Look for functions with high complexity (C+ rank)
            high_complexity = []
            total_functions = 0
            complex_functions = 0

            for line in lines:
                if line.strip() and not line.startswith(' ') and ' - ' in line:
                    total_functions += 1
                    # Check if complexity rank is C or higher
                    if any(rank in line for rank in [' - C', ' - D', ' - E', ' - F']):
                        high_complexity.append(line.strip())
                        complex_functions += 1

            if complex_functions == 0:
                return AuditResult(
                    check_name="code_complexity",
                    category="code_quality",
                    severity="low",
                    status="pass",
                    message=f"Code complexity is acceptable ({total_functions} functions analyzed)",
                    details="No functions with high complexity (rank C or above) found"
                )
            else:
                complexity_rate = (complex_functions / total_functions) * 100

                status = "warning" if complexity_rate < 10 else "fail"
                severity = "low" if complexity_rate < 10 else "medium"

                return AuditResult(
                    check_name="code_complexity",
                    category="code_quality",
                    severity=severity,
                    status=status,
                    message=f"Found {complex_functions}/{total_functions} functions with high complexity ({complexity_rate:.1f}%)",
                    details=f"Functions with complexity rank C or higher:\n" + '\n'.join(high_complexity[:10]),
                    recommendations=[
                        "Refactor complex functions (aim for complexity rank B or lower)",
                        "Break down large functions into smaller, focused functions",
                        "Consider using radon regularly: radon cc --min C backend agent",
                        "Set up pre-commit hooks to prevent complexity creep"
                    ]
                )
        else:
            return AuditResult(
                check_name="code_complexity",
                category="code_quality",
                severity="low",
                status="warning",
                message="Could not analyze code complexity",
                details=f"Radon command failed: {result.stderr}",
                recommendations=["Install radon: pip install radon", "Run manually: radon cc backend agent"]
            )

    except subprocess.TimeoutExpired:
        return AuditResult(
            check_name="code_complexity",
            category="code_quality",
            severity="low",
            status="warning",
            message="Code complexity check timed out",
            recommendations=["Run radon on individual directories", "Check for large files causing timeouts"]
        )
    except FileNotFoundError:
        return AuditResult(
            check_name="code_complexity",
            category="code_quality",
            severity="low",
            status="warning",
            message="Radon not installed - cannot check code complexity",
            details="The 'radon' complexity analyzer is not installed",
            recommendations=["Install radon: pip install radon", "Add radon to requirements-dev.txt"]
        )
    except Exception as e:
        return AuditResult(
            check_name="code_complexity",
            category="code_quality",
            severity="low",
            status="error",
            message=f"Code complexity check failed: {str(e)}",
            details=f"Unexpected error: {str(e)}"
        )


def check_docstring_coverage() -> AuditResult:
    """Check docstring coverage using interrogate."""
    try:
        # Check if interrogate is available
        result = subprocess.run(
            [sys.executable, "-m", "interrogate", "--verbose", "--fail-under", "80", "backend", "agent", "scripts"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60
        )

        if result.returncode == 0:
            # Parse output to get coverage percentage
            lines = result.stdout.split('\n')
            coverage_line = None
            for line in lines:
                if 'RESULT: ' in line and '%' in line:
                    coverage_line = line
                    break

            if coverage_line:
                # Extract percentage
                import re
                match = re.search(r'(\d+\.\d+)%', coverage_line)
                if match:
                    coverage = float(match.group(1))
                    if coverage >= 80:
                        return AuditResult(
                            check_name="docstring_coverage",
                            category="code_quality",
                            severity="low",
                            status="pass",
                            message=".1f",
                            details=f"Docstring coverage meets the 80% requirement: {coverage_line.strip()}"
                        )
                    else:
                        return AuditResult(
                            check_name="docstring_coverage",
                            category="code_quality",
                            severity="low",
                            status="fail",
                            message=".1f",
                            details=f"Docstring coverage is below 80% threshold: {coverage_line.strip()}",
                            recommendations=[
                                "Add docstrings to undocumented functions and classes",
                                "Use interrogate to identify missing docstrings: interrogate --verbose backend agent",
                                "Follow Google docstring format for consistency",
                                "Consider adding interrogate to CI pipeline"
                            ]
                        )

            return AuditResult(
                check_name="docstring_coverage",
                category="code_quality",
                severity="low",
                status="pass",
                message="Docstring coverage check passed",
                details="Interrogate check completed successfully"
            )
        else:
            # Parse failure output
            lines = result.stdout.split('\n')
            coverage_info = []
            for line in lines:
                if any(keyword in line.lower() for keyword in ['result:', 'total', 'missing']):
                    coverage_info.append(line.strip())

            return AuditResult(
                check_name="docstring_coverage",
                category="code_quality",
                severity="low",
                status="fail",
                message="Docstring coverage is below 80% threshold",
                details="Interrogate check failed:\n" + '\n'.join(coverage_info),
                recommendations=[
                    "Add docstrings to undocumented functions and classes",
                    "Run 'interrogate --verbose backend agent' to see detailed coverage",
                    "Focus on public APIs first (classes, functions, modules)"
                ]
            )

    except subprocess.TimeoutExpired:
        return AuditResult(
            check_name="docstring_coverage",
            category="code_quality",
            severity="low",
            status="warning",
            message="Docstring coverage check timed out",
            recommendations=["Run interrogate on individual directories"]
        )
    except FileNotFoundError:
        return AuditResult(
            check_name="docstring_coverage",
            category="code_quality",
            severity="low",
            status="warning",
            message="Interrogate not installed - cannot check docstring coverage",
            details="The 'interrogate' docstring analyzer is not installed",
            recommendations=["Install interrogate: pip install interrogate", "Add interrogate to requirements-dev.txt"]
        )
    except Exception as e:
        return AuditResult(
            check_name="docstring_coverage",
            category="code_quality",
            severity="low",
            status="error",
            message=f"Docstring coverage check failed: {str(e)}",
            details=f"Unexpected error: {str(e)}"
        )