"""
Test Coverage Audit Checks

This module contains all test coverage and quality audit checks for the JackSparrow project.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_test_execution() -> AuditResult:
    """Check test execution and basic functionality."""
    issues = []

    # Check if pytest is available
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            issues.append("pytest not available or not properly installed")
            return AuditResult(
                check_name="test_execution",
                category="tests",
                severity="high",
                status="fail",
                message="pytest not available - cannot run Python tests",
                details="pytest is required for running Python unit and integration tests",
                recommendations=["Install pytest: pip install pytest", "Add pytest to requirements-dev.txt"]
            )

    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append("pytest not found in PATH")

    # Run a quick test discovery to check test structure
    test_discovery = {}

    # Check backend tests
    backend_tests = project_root / "backend" / "tests"
    if backend_tests.exists():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "--quiet", "backend"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )

            if result.returncode == 0:
                # Parse collected tests
                lines = result.stdout.split('\n')
                test_files = [line for line in lines if 'test_' in line and '.py' in line]
                test_discovery['backend'] = len(test_files)
            else:
                issues.append("Failed to collect backend tests")

        except subprocess.TimeoutExpired:
            issues.append("Backend test discovery timed out")
    else:
        issues.append("backend/tests directory not found")

    # Check agent tests
    agent_tests = project_root / "agent" / "tests" / "unit" / "agent"
    if agent_tests.exists():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "--quiet", "agent"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )

            if result.returncode == 0:
                lines = result.stdout.split('\n')
                test_files = [line for line in lines if 'test_' in line and '.py' in line]
                test_discovery['agent'] = len(test_files)
            else:
                issues.append("Failed to collect agent tests")

        except subprocess.TimeoutExpired:
            issues.append("Agent test discovery timed out")

    # Check integration tests
    integration_tests = project_root / "tests" / "integration"
    if integration_tests.exists():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "--quiet", "tests/integration"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )

            if result.returncode == 0:
                lines = result.stdout.split('\n')
                test_files = [line for line in lines if 'test_' in line and '.py' in line]
                test_discovery['integration'] = len(test_files)

        except subprocess.TimeoutExpired:
            issues.append("Integration test discovery timed out")

    # Check functionality tests
    functionality_tests = project_root / "tests" / "functionality"
    if functionality_tests.exists():
        test_files = list(functionality_tests.glob("test_*.py"))
        test_discovery['functionality'] = len(test_files)

    # Check frontend tests
    frontend_dir = project_root / "frontend"
    if frontend_dir.exists():
        try:
            result = subprocess.run(
                ["npm", "test", "--", "--listTests"],
                capture_output=True,
                text=True,
                cwd=frontend_dir,
                timeout=30
            )

            if result.returncode == 0:
                lines = result.stdout.split('\n')
                test_files = [line for line in lines if '.test.' in line or '.spec.' in line]
                test_discovery['frontend'] = len(test_files)
            else:
                issues.append("Failed to list frontend tests")

        except (subprocess.TimeoutExpired, FileNotFoundError):
            issues.append("npm not available or frontend test discovery failed")

    # Analyze test distribution
    total_tests = sum(test_discovery.values())

    if total_tests == 0:
        issues.append("No tests found in the project")

    # Check for test structure issues
    if test_discovery.get('backend', 0) == 0:
        issues.append("No backend tests found")
    if test_discovery.get('agent', 0) == 0:
        issues.append("No agent tests found")
    if test_discovery.get('integration', 0) == 0:
        issues.append("No integration tests found")

    # Check test-to-code ratio (rough estimate)
    code_files = []
    for root, dirs, files in os.walk(project_root):
        if any(skip in root for skip in ['__pycache__', 'node_modules', '.git', 'logs']):
            continue
        for file in files:
            if file.endswith('.py') and not file.startswith('test_'):
                if 'backend' in root or 'agent' in root or 'scripts' in root:
                    code_files.append(file)

    if code_files and total_tests > 0:
        code_to_test_ratio = len(code_files) / total_tests
        if code_to_test_ratio > 10:  # More than 10 code files per test file
            issues.append(".2f")

    if not issues:
        test_summary = ", ".join([f"{component}: {count}" for component, count in test_discovery.items()])

        return AuditResult(
            check_name="test_execution",
            category="tests",
            severity="high",
            status="pass",
            message=f"Test structure is adequate ({total_tests} test files found)",
            details=f"Test files by component: {test_summary}"
        )
    else:
        severity = "high" if "No tests found" in str(issues) else "medium"

        return AuditResult(
            check_name="test_execution",
            category="tests",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} test execution issues",
            details="Issues found:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Add unit tests for backend and agent components",
                "Implement integration tests for component interactions",
                "Add frontend tests for React components",
                "Aim for at least 1 test file per 5-10 code files",
                "Use pytest fixtures for test data management",
                "Add test coverage reporting to CI/CD"
            ]
        )


def check_test_coverage() -> AuditResult:
    """Check test coverage analysis."""
    issues = []

    # Check if coverage tools are available
    coverage_available = False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--cov", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        coverage_available = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    if not coverage_available:
        return AuditResult(
            check_name="test_coverage",
            category="tests",
            severity="high",
            status="warning",
            message="Coverage tools not available - cannot measure test coverage",
            details="pytest-cov is required for measuring code coverage",
            recommendations=["Install pytest-cov: pip install pytest-cov", "Add pytest-cov to requirements-dev.txt"]
        )

    # Run coverage analysis
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--cov=backend", "--cov=agent", "--cov-report=json", "--cov-fail-under=1"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=120
        )

        coverage_data = None
        if result.returncode == 0 or "coverage" in result.stdout:
            # Try to find coverage.json
            coverage_file = project_root / "coverage.json"
            if coverage_file.exists():
                try:
                    with open(coverage_file, 'r', encoding='utf-8') as f:
                        coverage_data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

        if coverage_data:
            # Parse coverage data
            totals = coverage_data.get('totals', {})
            covered_lines = totals.get('covered_lines', 0)
            num_statements = totals.get('num_statements', 1)
            coverage_percent = totals.get('percent_covered', 0)

            # Check coverage by component
            files = coverage_data.get('files', {})
            component_coverage = {
                'backend': [],
                'agent': []
            }

            for file_path, file_data in files.items():
                file_percent = file_data.get('summary', {}).get('percent_covered', 0)

                if 'backend' in file_path:
                    component_coverage['backend'].append(file_percent)
                elif 'agent' in file_path:
                    component_coverage['agent'].append(file_percent)

            # Calculate averages
            backend_avg = sum(component_coverage['backend']) / len(component_coverage['backend']) if component_coverage['backend'] else 0
            agent_avg = sum(component_coverage['agent']) / len(component_coverage['agent']) if component_coverage['agent'] else 0

            # Check critical path coverage (risk management, trading logic)
            critical_files = []
            for file_path in files.keys():
                if any(critical in file_path.lower() for critical in ['risk', 'trade', 'position', 'order']):
                    file_cov = files[file_path].get('summary', {}).get('percent_covered', 0)
                    if file_cov < 80:  # Less than 80% coverage for critical files
                        critical_files.append(f"{Path(file_path).name}: {file_cov:.1f}%")

            if critical_files:
                issues.append(f"Low coverage on critical files: {', '.join(critical_files[:3])}")

            if coverage_percent < 80:
                issues.append(".1f")

            if backend_avg < 70:
                issues.append(".1f")

            if agent_avg < 70:
                issues.append(".1f")

            # Check for completely uncovered files
            uncovered_files = [
                Path(file_path).name
                for file_path, file_data in files.items()
                if file_data.get('summary', {}).get('percent_covered', 0) == 0
            ]

            if uncovered_files:
                issues.append(f"Completely uncovered files: {', '.join(uncovered_files[:5])}")
                if len(uncovered_files) > 5:
                    issues[-1] += f" (+{len(uncovered_files) - 5} more)"

            if not issues:
                return AuditResult(
                    check_name="test_coverage",
                    category="tests",
                    severity="high",
                    status="pass",
                    message=".1f",
                    details=".1f"
                )
            else:
                severity = "high" if coverage_percent < 50 else "medium"

                return AuditResult(
                    check_name="test_coverage",
                    category="tests",
                    severity=severity,
                    status="fail",
                    message=f"Test coverage issues found ({len(issues)} issues)",
                    details="Coverage issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
                    recommendations=[
                        "Aim for 80%+ overall test coverage",
                        "Ensure 100% coverage for critical paths (risk management, trading logic)",
                        "Add tests for uncovered files and functions",
                        "Use coverage.py for detailed coverage reports",
                        "Set up coverage badges in CI/CD",
                        "Review coverage exclusions in .coveragerc"
                    ]
                )

        else:
            # Fallback: check if tests ran at all
            if result.returncode == 0:
                return AuditResult(
                    check_name="test_coverage",
                    category="tests",
                    severity="medium",
                    status="warning",
                    message="Tests executed but coverage data not available",
                    details="pytest ran successfully but coverage report could not be generated",
                    recommendations=["Check pytest-cov configuration", "Ensure coverage.json is generated"]
                )
            else:
                issues.append("Coverage analysis failed to run")

    except subprocess.TimeoutExpired:
        issues.append("Coverage analysis timed out")

    except Exception as e:
        issues.append(f"Coverage analysis failed: {str(e)}")

    return AuditResult(
        check_name="test_coverage",
        category="tests",
        severity="high",
        status="error",
        message="Test coverage analysis failed",
        details="Issues encountered:\n" + '\n'.join(f"- {issue}" for issue in issues),
        recommendations=["Install pytest-cov: pip install pytest-cov", "Run coverage manually: pytest --cov=backend --cov=agent"]
    )


def check_test_quality() -> AuditResult:
    """Check test quality and best practices."""
    issues = []

    # Analyze test files for quality issues
    test_files = []

    # Find all test files
    for root, dirs, files in os.walk(project_root):
        if any(skip in root for skip in ['__pycache__', 'node_modules', '.git']):
            continue

        for file in files:
            if file.startswith('test_') and file.endswith('.py'):
                test_files.append(Path(root) / file)

    if not test_files:
        return AuditResult(
            check_name="test_quality",
            category="tests",
            severity="high",
            status="fail",
            message="No test files found to analyze",
            recommendations=["Create test files following the test_*.py naming convention"]
        )

    # Analyze each test file
    quality_metrics = {
        'total_tests': 0,
        'files_with_fixtures': 0,
        'files_with_asserts': 0,
        'files_with_parametrize': 0,
        'files_with_mocks': 0,
        'empty_test_files': 0,
        'tests_without_asserts': [],
        'duplicate_test_names': [],
    }

    test_names = set()

    for test_file in test_files[:50]:  # Limit to first 50 files for performance
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Count test functions
                test_functions = re.findall(r'def test_\w+', content)
                quality_metrics['total_tests'] += len(test_functions)

                # Check for test fixtures
                if '@pytest.fixture' in content or 'fixture' in content:
                    quality_metrics['files_with_fixtures'] += 1

                # Check for parametrize
                if '@pytest.mark.parametrize' in content:
                    quality_metrics['files_with_parametrize'] += 1

                # Check for mocking
                if any(mock in content for mock in ['mock', 'MagicMock', 'patch']):
                    quality_metrics['files_with_mocks'] += 1

                # Check for assertions
                assert_count = len(re.findall(r'\bassert\s', content))
                if assert_count > 0:
                    quality_metrics['files_with_asserts'] += 1

                # Check for tests without assertions
                for func_match in re.finditer(r'def (test_\w+)', content):
                    func_name = func_match.group(1)
                    # Find function content
                    func_start = func_match.end()
                    next_func = re.search(r'def test_\w+', content[func_start:])
                    func_end = next_func.start() + func_start if next_func else len(content)
                    func_content = content[func_start:func_end]

                    if 'assert' not in func_content and 'pytest.raises' not in func_content:
                        quality_metrics['tests_without_asserts'].append(f"{test_file.name}::{func_name}")

                # Check for duplicate test names
                for func_match in re.finditer(r'def (test_\w+)', content):
                    func_name = func_match.group(1)
                    if func_name in test_names:
                        quality_metrics['duplicate_test_names'].append(func_name)
                    else:
                        test_names.add(func_name)

                # Check for empty test files
                if not test_functions:
                    quality_metrics['empty_test_files'] += 1

        except (UnicodeDecodeError, OSError) as e:
            issues.append(f"Could not analyze {test_file.name}: {e}")

    # Analyze quality metrics
    total_files = len(test_files)

    if quality_metrics['empty_test_files'] > 0:
        issues.append(f"{quality_metrics['empty_test_files']} empty test files found")

    if quality_metrics['tests_without_asserts']:
        issues.append(f"{len(quality_metrics['tests_without_asserts'])} tests without assertions")

    if quality_metrics['duplicate_test_names']:
        issues.append(f"Duplicate test names found: {', '.join(set(quality_metrics['duplicate_test_names'][:3]))}")

    # Calculate quality scores
    fixture_ratio = quality_metrics['files_with_fixtures'] / total_files if total_files > 0 else 0
    parametrize_ratio = quality_metrics['files_with_parametrize'] / total_files if total_files > 0 else 0
    mock_ratio = quality_metrics['files_with_mocks'] / total_files if total_files > 0 else 0

    if fixture_ratio < 0.3:  # Less than 30% of test files use fixtures
        issues.append(".1f")

    if parametrize_ratio < 0.2:  # Less than 20% use parametrization
        issues.append(".1f")

    if mock_ratio < 0.4:  # Less than 40% use mocking (may indicate integration tests)
        issues.append("Low usage of mocking - consider if tests are properly isolated")

    # Check for test organization
    test_dirs = [d for d in project_root.glob("**/tests") if d.is_dir()]
    if len(test_dirs) < 3:  # Should have unit, integration, e2e at minimum
        issues.append("Limited test directory structure - consider organizing by test type")

    if not issues:
        return AuditResult(
            check_name="test_quality",
            category="tests",
            severity="medium",
            status="pass",
            message=f"Test quality is good ({quality_metrics['total_tests']} tests analyzed)",
            details=f"Quality metrics: {quality_metrics['files_with_fixtures']}/{total_files} files use fixtures, {quality_metrics['files_with_parametrize']}/{total_files} use parametrization"
        )
    else:
        severity = "high" if any("empty" in issue or "without assertions" in issue for issue in issues) else "medium"

        return AuditResult(
            check_name="test_quality",
            category="tests",
            severity=severity,
            status="fail",
            message=f"Found {len(issues)} test quality issues",
            details="Quality issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=[
                "Add assertions to all test functions",
                "Use pytest fixtures for test data setup",
                "Use @pytest.mark.parametrize for testing multiple inputs",
                "Use mocking to isolate units under test",
                "Follow naming conventions: test_function_name",
                "Organize tests by type (unit, integration, e2e)",
                "Remove or fix empty test files"
            ]
        )