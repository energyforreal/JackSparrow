#!/usr/bin/env python3
"""
Comprehensive Audit Script for JackSparrow Trading Agent

This script performs a complete audit of all project components including:
- Code quality and standards
- Security vulnerabilities
- Dependency management
- Test coverage
- Documentation completeness
- Configuration validation
- Infrastructure health
- Database and model integrity
- Service operations
- Performance metrics

Usage:
    python scripts/comprehensive_audit.py [--verbose] [--quick] [--category CATEGORY]

Options:
    --verbose, -v    Enable verbose output
    --quick, -q      Run only critical checks (skip time-consuming ones)
    --category, -c   Run only specific category (e.g., security, code_quality)
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import existing validation modules
try:
    from scripts.validate_env import validate_environment
except ImportError:
    validate_environment = None

try:
    from tools.commands.validate_prerequisites import main as validate_prerequisites
except ImportError:
    validate_prerequisites = None

try:
    from tools.commands.health_check import main as health_check
except ImportError:
    health_check = None


@dataclass
class AuditResult:
    """Result of an individual audit check."""
    check_name: str
    category: str
    severity: str  # critical, high, medium, low, info
    status: str    # pass, fail, warning, error, skip
    message: str
    details: Optional[str] = None
    duration: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditCategory:
    """Collection of audit checks for a category."""
    name: str
    description: str
    checks: List[AuditResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate for this category."""
        if not self.checks:
            return 0.0
        passed = sum(1 for check in self.checks if check.status in ['pass', 'warning'])
        return (passed / len(self.checks)) * 100

    @property
    def critical_failures(self) -> int:
        """Count critical failures."""
        return sum(1 for check in self.checks
                  if check.severity == 'critical' and check.status == 'fail')

    @property
    def high_failures(self) -> int:
        """Count high-priority failures."""
        return sum(1 for check in self.checks
                  if check.severity == 'high' and check.status == 'fail')


@dataclass
class AuditReport:
    """Complete audit report."""
    timestamp: datetime
    categories: Dict[str, AuditCategory] = field(default_factory=dict)
    execution_time: float = 0.0
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    critical_issues: int = 0
    high_issues: int = 0

    @property
    def overall_health_score(self) -> float:
        """Calculate overall health score (0-100)."""
        if self.total_checks == 0:
            return 0.0

        # Weight by severity
        weighted_score = 0.0
        total_weight = 0.0

        severity_weights = {
            'critical': 10,
            'high': 7,
            'medium': 4,
            'low': 2,
            'info': 1
        }

        for category in self.categories.values():
            for check in category.checks:
                weight = severity_weights.get(check.severity, 1)
                total_weight += weight

                if check.status in ['pass', 'warning']:
                    weighted_score += weight
                elif check.status == 'skip':
                    weighted_score += weight * 0.5  # Partial credit for skipped

        return (weighted_score / total_weight) * 100 if total_weight > 0 else 0.0

    def add_result(self, result: AuditResult):
        """Add an audit result to the report."""
        if result.category not in self.categories:
            self.categories[result.category] = AuditCategory(
                name=result.category,
                description=f"Checks for {result.category.replace('_', ' ')}"
            )

        self.categories[result.category].checks.append(result)
        self.total_checks += 1

        if result.status in ['pass', 'warning']:
            self.passed_checks += 1
        elif result.status == 'fail':
            self.failed_checks += 1

        if result.severity == 'critical' and result.status == 'fail':
            self.critical_issues += 1
        elif result.severity == 'high' and result.status == 'fail':
            self.high_issues += 1


class ComprehensiveAuditor:
    """Main auditor class that orchestrates all audit checks."""

    def __init__(self, verbose: bool = False, quick_mode: bool = False):
        self.verbose = verbose
        self.quick_mode = quick_mode
        self.project_root = Path(__file__).parent.parent
        self.report = AuditReport(timestamp=datetime.now())

        # Create audit_checks directory if it doesn't exist
        self.checks_dir = self.project_root / "scripts" / "audit_checks"
        self.checks_dir.mkdir(exist_ok=True)

        # Initialize check modules
        self.check_modules = {}
        self._load_check_functions()

    def log(self, message: str, level: str = "info"):
        """Log a message if verbose mode is enabled."""
        if self.verbose or level in ["error", "warning"]:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {level.upper()}: {message}")

    def load_check_module(self, module_name: str) -> Optional[Any]:
        """Load an audit check module dynamically."""
        module_path = self.checks_dir / f"{module_name}.py"
        if not module_path.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except Exception as e:
            self.log(f"Failed to load check module {module_name}: {e}", "error")

        return None

    def run_audit_check(self, category: str, check_name: str,
                        check_func, *args, **kwargs) -> AuditResult:
        """Run a single audit check and return the result."""
        start_time = time.time()

        try:
            self.log(f"Running {category}.{check_name}...")
            result = check_func(*args, **kwargs)
            if not isinstance(result, AuditResult):
                # Convert legacy result format
                result = AuditResult(
                    check_name=check_name,
                    category=category,
                    severity=result.get('severity', 'medium') if hasattr(result, 'get') else 'medium',
                    status=result.get('status', 'pass') if hasattr(result, 'get') else 'pass',
                    message=result.get('message', 'Check completed') if hasattr(result, 'get') else 'Check completed',
                    details=result.get('details') if hasattr(result, 'get') else None,
                    recommendations=result.get('recommendations', []) if hasattr(result, 'get') else [],
                    metadata=result.get('metadata', {}) if hasattr(result, 'get') else {}
                )
        except Exception as e:
            result = AuditResult(
                check_name=check_name,
                category=category,
                severity='high',
                status='error',
                message=f"Check failed with exception: {str(e)}",
                duration=time.time() - start_time
            )

        result.duration = time.time() - start_time
        return result

    async def run_category_checks(self, category: str,
                                 checks: List[Tuple[str, callable]]) -> List[AuditResult]:
        """Run all checks for a category."""
        results = []

        for check_name, check_func in checks:
            # Skip time-consuming checks in quick mode
            if self.quick_mode and hasattr(check_func, '_audit_slow'):
                self.log(f"Skipping {category}.{check_name} (quick mode)")
                result = AuditResult(
                    check_name=check_name,
                    category=category,
                    severity='low',
                    status='skip',
                    message="Skipped in quick mode"
                )
                results.append(result)
                continue

            result = self.run_audit_check(category, check_name, check_func)
            results.append(result)
            self.report.add_result(result)

        return results

    async def audit_code_quality(self) -> List[AuditResult]:
        """Audit code quality and standards."""
        checks = [
            ("python_formatting", self._check_python_formatting),
            ("python_linting", self._check_python_linting),
            ("typescript_quality", self._check_typescript_quality),
            ("code_complexity", self._check_code_complexity),
            ("docstring_coverage", self._check_docstring_coverage),
        ]
        return await self.run_category_checks("code_quality", checks)

    async def audit_security(self) -> List[AuditResult]:
        """Audit security vulnerabilities and practices."""
        checks = [
            ("secrets_scan", self._check_secrets_scan),
            ("dependency_vulnerabilities", self._check_dependency_vulnerabilities),
            ("security_practices", self._check_security_practices),
            ("api_security", self._check_api_security),
        ]
        return await self.run_category_checks("security", checks)

    async def audit_dependencies(self) -> List[AuditResult]:
        """Audit dependency management."""
        checks = [
            ("python_dependencies", self._check_python_dependencies),
            ("nodejs_dependencies", self._check_nodejs_dependencies),
            ("docker_dependencies", self._check_docker_dependencies),
        ]
        return await self.run_category_checks("dependencies", checks)

    async def audit_tests(self) -> List[AuditResult]:
        """Audit test coverage and quality."""
        checks = [
            ("test_execution", self._check_test_execution),
            ("test_coverage", self._check_test_coverage),
            ("test_quality", self._check_test_quality),
        ]
        return await self.run_category_checks("tests", checks)

    async def audit_documentation(self) -> List[AuditResult]:
        """Audit documentation completeness and quality."""
        checks = [
            ("documentation_completeness", self._check_documentation_completeness),
            ("documentation_quality", self._check_documentation_quality),
            ("broken_links", self._check_broken_links),
        ]
        return await self.run_category_checks("documentation", checks)

    async def audit_configuration(self) -> List[AuditResult]:
        """Audit configuration and environment."""
        checks = [
            ("environment_variables", self._check_environment_variables),
            ("configuration_files", self._check_configuration_files),
        ]
        return await self.run_category_checks("configuration", checks)

    async def audit_infrastructure(self) -> List[AuditResult]:
        """Audit infrastructure and deployment."""
        checks = [
            ("docker_configuration", self._check_docker_configuration),
            ("cicd_pipeline", self._check_cicd_pipeline),
        ]
        return await self.run_category_checks("infrastructure", checks)

    async def audit_database_and_models(self) -> List[AuditResult]:
        """Audit database and ML models."""
        checks = [
            ("database_schema", self._check_database_schema),
            ("model_files", self._check_model_files),
        ]
        return await self.run_category_checks("database_models", checks)

    async def audit_service_health(self) -> List[AuditResult]:
        """Audit service health and operations."""
        checks = [
            ("service_health", self._check_service_health),
            ("log_analysis", self._check_log_analysis),
        ]
        return await self.run_category_checks("service_health", checks)

    async def audit_git_repository(self) -> List[AuditResult]:
        """Audit Git repository health."""
        checks = [
            ("repository_status", self._check_repository_status),
            ("gitignore_completeness", self._check_gitignore_completeness),
        ]
        return await self.run_category_checks("git_repository", checks)

    async def audit_performance(self) -> List[AuditResult]:
        """Audit performance metrics."""
        checks = [
            ("performance_baselines", self._check_performance_baselines),
        ]
        return await self.run_category_checks("performance", checks)

    async def audit_error_handling(self) -> List[AuditResult]:
        """Audit error handling and resilience."""
        checks = [
            ("error_handling_patterns", self._check_error_handling_patterns),
            ("resilience_mechanisms", self._check_resilience_mechanisms),
        ]
        return await self.run_category_checks("error_handling", checks)

    async def audit_api_integration(self) -> List[AuditResult]:
        """Audit API and integration points."""
        checks = [
            ("api_endpoints", self._check_api_endpoints),
            ("websocket_communication", self._check_websocket_communication),
            ("frontend_backend_integration", self._check_frontend_backend_integration),
        ]
        return await self.run_category_checks("api_integration", checks)

    async def audit_ml_model_management(self) -> List[AuditResult]:
        """Audit ML model management."""
        checks = [
            ("model_registry", self._check_model_registry),
            ("model_discovery", self._check_model_discovery),
        ]
        return await self.run_category_checks("ml_model_management", checks)

    async def run_audit(self, categories: Optional[List[str]] = None) -> AuditReport:
        """Run the complete audit or specific categories."""
        start_time = time.time()
        self.log("Starting comprehensive audit...")

        # Define all audit categories
        all_categories = {
            "code_quality": self.audit_code_quality,
            "security": self.audit_security,
            "dependencies": self.audit_dependencies,
            "tests": self.audit_tests,
            "documentation": self.audit_documentation,
            "configuration": self.audit_configuration,
            "infrastructure": self.audit_infrastructure,
            "database_models": self.audit_database_and_models,
            "service_health": self.audit_service_health,
            "git_repository": self.audit_git_repository,
            "performance": self.audit_performance,
            "error_handling": self.audit_error_handling,
            "api_integration": self.audit_api_integration,
            "ml_model_management": self.audit_ml_model_management,
        }

        # Filter categories if specified
        if categories:
            audit_categories = {k: v for k, v in all_categories.items() if k in categories}
        else:
            audit_categories = all_categories

        # Run all categories
        for category_name, audit_func in audit_categories.items():
            self.log(f"Auditing {category_name}...")
            await audit_func()

        self.report.execution_time = time.time() - start_time
        self.log(".2f")

        return self.report

    # Import check functions from modules
    def _load_check_functions(self):
        """Load check functions from audit check modules."""
        try:
            from scripts.audit_checks import code_quality
            self._check_python_formatting = code_quality.check_python_formatting
            self._check_python_linting = code_quality.check_python_linting
            self._check_typescript_quality = code_quality.check_typescript_quality
            self._check_code_complexity = code_quality.check_code_complexity
            self._check_docstring_coverage = code_quality.check_docstring_coverage
        except ImportError as e:
            self.log(f"Failed to import code quality checks: {e}", "warning")

        try:
            from scripts.audit_checks import security
            self._check_secrets_scan = security.check_secrets_scan
            self._check_dependency_vulnerabilities = security.check_dependency_vulnerabilities
            self._check_security_practices = security.check_security_practices
            self._check_api_security = security.check_api_security
        except ImportError as e:
            self.log(f"Failed to import security checks: {e}", "warning")

        try:
            from scripts.audit_checks import dependencies
            self._check_python_dependencies = dependencies.check_python_dependencies
            self._check_nodejs_dependencies = dependencies.check_nodejs_dependencies
            self._check_docker_dependencies = dependencies.check_docker_dependencies
        except ImportError as e:
            self.log(f"Failed to import dependency checks: {e}", "warning")

        try:
            from scripts.audit_checks import tests
            self._check_test_execution = tests.check_test_execution
            self._check_test_coverage = tests.check_test_coverage
            self._check_test_quality = tests.check_test_quality
        except ImportError as e:
            self.log(f"Failed to import test checks: {e}", "warning")

        try:
            from scripts.audit_checks import documentation
            self._check_documentation_completeness = documentation.check_documentation_completeness
            self._check_documentation_quality = documentation.check_documentation_quality
            self._check_broken_links = documentation.check_broken_links
        except ImportError as e:
            self.log(f"Failed to import documentation checks: {e}", "warning")

        try:
            from scripts.audit_checks import configuration
            self._check_environment_variables = configuration.check_environment_variables
            self._check_configuration_files = configuration.check_configuration_files
        except ImportError as e:
            self.log(f"Failed to import configuration checks: {e}", "warning")

        try:
            from scripts.audit_checks import infrastructure
            self._check_docker_configuration = infrastructure.check_docker_configuration
            self._check_cicd_pipeline = infrastructure.check_cicd_pipeline
        except ImportError as e:
            self.log(f"Failed to import infrastructure checks: {e}", "warning")

        try:
            from scripts.audit_checks import database_models
            self._check_database_schema = database_models.check_database_schema
            self._check_model_files = database_models.check_model_files
        except ImportError as e:
            self.log(f"Failed to import database/model checks: {e}", "warning")

        try:
            from scripts.audit_checks import service_health
            self._check_service_health = service_health.check_service_health
            self._check_log_analysis = service_health.check_log_analysis
        except ImportError as e:
            self.log(f"Failed to import service health checks: {e}", "warning")

        try:
            from scripts.audit_checks import git_repository
            self._check_repository_status = git_repository.check_repository_status
            self._check_gitignore_completeness = git_repository.check_gitignore_completeness
        except ImportError as e:
            self.log(f"Failed to import git repository checks: {e}", "warning")

        try:
            from scripts.audit_checks import performance
            self._check_performance_baselines = performance.check_performance_baselines
        except ImportError as e:
            self.log(f"Failed to import performance checks: {e}", "warning")

        try:
            from scripts.audit_checks import error_handling
            self._check_error_handling_patterns = error_handling.check_error_handling_patterns
            self._check_resilience_mechanisms = error_handling.check_resilience_mechanisms
        except ImportError as e:
            self.log(f"Failed to import error handling checks: {e}", "warning")

        try:
            from scripts.audit_checks import api_integration
            self._check_api_endpoints = api_integration.check_api_endpoints
            self._check_websocket_communication = api_integration.check_websocket_communication
            self._check_frontend_backend_integration = api_integration.check_frontend_backend_integration
        except ImportError as e:
            self.log(f"Failed to import API integration checks: {e}", "warning")

        try:
            from scripts.audit_checks import ml_model_management
            self._check_model_registry = ml_model_management.check_model_registry
            self._check_model_discovery = ml_model_management.check_model_discovery
        except ImportError as e:
            self.log(f"Failed to import ML model management checks: {e}", "warning")

    # Placeholder check methods - will be replaced by loaded functions
    def _check_python_formatting(self) -> AuditResult:
        """Check Python code formatting."""
        return AuditResult(
            check_name="python_formatting",
            category="code_quality",
            severity="medium",
            status="skip",
            message="Python formatting check not yet implemented"
        )

    def _check_python_linting(self) -> AuditResult:
        """Check Python linting."""
        return AuditResult(
            check_name="python_linting",
            category="code_quality",
            severity="medium",
            status="skip",
            message="Python linting check not yet implemented"
        )

    def _check_typescript_quality(self) -> AuditResult:
        """Check TypeScript/React code quality."""
        return AuditResult(
            check_name="typescript_quality",
            category="code_quality",
            severity="medium",
            status="skip",
            message="TypeScript quality check not yet implemented"
        )

    def _check_code_complexity(self) -> AuditResult:
        """Check code complexity."""
        return AuditResult(
            check_name="code_complexity",
            category="code_quality",
            severity="low",
            status="skip",
            message="Code complexity check not yet implemented"
        )

    def _check_docstring_coverage(self) -> AuditResult:
        """Check docstring coverage."""
        return AuditResult(
            check_name="docstring_coverage",
            category="code_quality",
            severity="low",
            status="skip",
            message="Docstring coverage check not yet implemented"
        )

    def _check_secrets_scan(self) -> AuditResult:
        """Scan for hardcoded secrets."""
        return AuditResult(
            check_name="secrets_scan",
            category="security",
            severity="high",
            status="skip",
            message="Secrets scan not yet implemented"
        )

    def _check_dependency_vulnerabilities(self) -> AuditResult:
        """Check for dependency vulnerabilities."""
        return AuditResult(
            check_name="dependency_vulnerabilities",
            category="security",
            severity="high",
            status="skip",
            message="Dependency vulnerabilities check not yet implemented"
        )

    def _check_security_practices(self) -> AuditResult:
        """Check security best practices."""
        return AuditResult(
            check_name="security_practices",
            category="security",
            severity="medium",
            status="skip",
            message="Security practices check not yet implemented"
        )

    def _check_api_security(self) -> AuditResult:
        """Check API security."""
        return AuditResult(
            check_name="api_security",
            category="security",
            severity="high",
            status="skip",
            message="API security check not yet implemented"
        )

    def _check_python_dependencies(self) -> AuditResult:
        """Check Python dependencies."""
        return AuditResult(
            check_name="python_dependencies",
            category="dependencies",
            severity="medium",
            status="skip",
            message="Python dependencies check not yet implemented"
        )

    def _check_nodejs_dependencies(self) -> AuditResult:
        """Check Node.js dependencies."""
        return AuditResult(
            check_name="nodejs_dependencies",
            category="dependencies",
            severity="medium",
            status="skip",
            message="Node.js dependencies check not yet implemented"
        )

    def _check_docker_dependencies(self) -> AuditResult:
        """Check Docker dependencies."""
        return AuditResult(
            check_name="docker_dependencies",
            category="dependencies",
            severity="low",
            status="skip",
            message="Docker dependencies check not yet implemented"
        )

    def _check_test_execution(self) -> AuditResult:
        """Check test execution."""
        return AuditResult(
            check_name="test_execution",
            category="tests",
            severity="high",
            status="skip",
            message="Test execution check not yet implemented"
        )

    def _check_test_coverage(self) -> AuditResult:
        """Check test coverage."""
        return AuditResult(
            check_name="test_coverage",
            category="tests",
            severity="high",
            status="skip",
            message="Test coverage check not yet implemented"
        )

    def _check_test_quality(self) -> AuditResult:
        """Check test quality."""
        return AuditResult(
            check_name="test_quality",
            category="tests",
            severity="medium",
            status="skip",
            message="Test quality check not yet implemented"
        )

    def _check_documentation_completeness(self) -> AuditResult:
        """Check documentation completeness."""
        return AuditResult(
            check_name="documentation_completeness",
            category="documentation",
            severity="medium",
            status="skip",
            message="Documentation completeness check not yet implemented"
        )

    def _check_documentation_quality(self) -> AuditResult:
        """Check documentation quality."""
        return AuditResult(
            check_name="documentation_quality",
            category="documentation",
            severity="low",
            status="skip",
            message="Documentation quality check not yet implemented"
        )

    def _check_broken_links(self) -> AuditResult:
        """Check for broken links in documentation."""
        return AuditResult(
            check_name="broken_links",
            category="documentation",
            severity="low",
            status="skip",
            message="Broken links check not yet implemented"
        )

    def _check_environment_variables(self) -> AuditResult:
        """Check environment variables."""
        return AuditResult(
            check_name="environment_variables",
            category="configuration",
            severity="high",
            status="skip",
            message="Environment variables check not yet implemented"
        )

    def _check_configuration_files(self) -> AuditResult:
        """Check configuration files."""
        return AuditResult(
            check_name="configuration_files",
            category="configuration",
            severity="medium",
            status="skip",
            message="Configuration files check not yet implemented"
        )

    def _check_docker_configuration(self) -> AuditResult:
        """Check Docker configuration."""
        return AuditResult(
            check_name="docker_configuration",
            category="infrastructure",
            severity="high",
            status="skip",
            message="Docker configuration check not yet implemented"
        )

    def _check_cicd_pipeline(self) -> AuditResult:
        """Check CI/CD pipeline."""
        return AuditResult(
            check_name="cicd_pipeline",
            category="infrastructure",
            severity="medium",
            status="skip",
            message="CI/CD pipeline check not yet implemented"
        )

    def _check_database_schema(self) -> AuditResult:
        """Check database schema."""
        return AuditResult(
            check_name="database_schema",
            category="database_models",
            severity="high",
            status="skip",
            message="Database schema check not yet implemented"
        )

    def _check_model_files(self) -> AuditResult:
        """Check ML model files."""
        return AuditResult(
            check_name="model_files",
            category="database_models",
            severity="high",
            status="skip",
            message="Model files check not yet implemented"
        )

    def _check_service_health(self) -> AuditResult:
        """Check service health."""
        return AuditResult(
            check_name="service_health",
            category="service_health",
            severity="critical",
            status="skip",
            message="Service health check not yet implemented"
        )

    def _check_log_analysis(self) -> AuditResult:
        """Analyze logs for issues."""
        return AuditResult(
            check_name="log_analysis",
            category="service_health",
            severity="medium",
            status="skip",
            message="Log analysis check not yet implemented"
        )

    def _check_repository_status(self) -> AuditResult:
        """Check Git repository status."""
        return AuditResult(
            check_name="repository_status",
            category="git_repository",
            severity="low",
            status="skip",
            message="Repository status check not yet implemented"
        )

    def _check_gitignore_completeness(self) -> AuditResult:
        """Check .gitignore completeness."""
        return AuditResult(
            check_name="gitignore_completeness",
            category="git_repository",
            severity="low",
            status="skip",
            message="Gitignore completeness check not yet implemented"
        )

    def _check_performance_baselines(self) -> AuditResult:
        """Check performance baselines."""
        return AuditResult(
            check_name="performance_baselines",
            category="performance",
            severity="medium",
            status="skip",
            message="Performance baselines check not yet implemented"
        )

    def _check_error_handling_patterns(self) -> AuditResult:
        """Check error handling patterns."""
        return AuditResult(
            check_name="error_handling_patterns",
            category="error_handling",
            severity="medium",
            status="skip",
            message="Error handling patterns check not yet implemented"
        )

    def _check_resilience_mechanisms(self) -> AuditResult:
        """Check resilience mechanisms."""
        return AuditResult(
            check_name="resilience_mechanisms",
            category="error_handling",
            severity="high",
            status="skip",
            message="Resilience mechanisms check not yet implemented"
        )

    def _check_api_endpoints(self) -> AuditResult:
        """Check API endpoints."""
        return AuditResult(
            check_name="api_endpoints",
            category="api_integration",
            severity="high",
            status="skip",
            message="API endpoints check not yet implemented"
        )

    def _check_websocket_communication(self) -> AuditResult:
        """Check WebSocket communication."""
        return AuditResult(
            check_name="websocket_communication",
            category="api_integration",
            severity="high",
            status="skip",
            message="WebSocket communication check not yet implemented"
        )

    def _check_frontend_backend_integration(self) -> AuditResult:
        """Check frontend-backend integration."""
        return AuditResult(
            check_name="frontend_backend_integration",
            category="api_integration",
            severity="high",
            status="skip",
            message="Frontend-backend integration check not yet implemented"
        )

    def _check_model_registry(self) -> AuditResult:
        """Check model registry."""
        return AuditResult(
            check_name="model_registry",
            category="ml_model_management",
            severity="high",
            status="skip",
            message="Model registry check not yet implemented"
        )

    def _check_model_discovery(self) -> AuditResult:
        """Check model discovery."""
        return AuditResult(
            check_name="model_discovery",
            category="ml_model_management",
            severity="high",
            status="skip",
            message="Model discovery check not yet implemented"
        )


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Comprehensive Audit for JackSparrow Trading Agent")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--quick", "-q", action="store_true", help="Run only critical checks")
    parser.add_argument("--category", "-c", action="append", help="Run only specific category")
    parser.add_argument("--output-dir", default="logs/audit", help="Output directory for reports")

    args = parser.parse_args()

    # Create auditor
    auditor = ComprehensiveAuditor(verbose=args.verbose, quick_mode=args.quick)

    # Run audit
    report = await auditor.run_audit(categories=args.category)

    # Generate reports
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = report.timestamp.strftime("%Y%m%d_%H%M%S")

    # JSON report
    json_file = output_dir / f"comprehensive_audit_{timestamp}.json"
    with open(json_file, 'w') as f:
        json.dump(report.__dict__, f, indent=2, default=str)

    # Markdown report
    md_file = output_dir / f"comprehensive_audit_{timestamp}.md"
    with open(md_file, 'w') as f:
        f.write(generate_markdown_report(report))

    print("\nAudit completed!")
    print(f"  JSON Report: {json_file}")
    print(f"  Markdown Report: {md_file}")
    print(".1f")
    print(".1f")
    if report.critical_issues > 0:
        print(f"  [CRITICAL] Issues: {report.critical_issues}")
    if report.high_issues > 0:
        print(f"  [HIGH] Priority Issues: {report.high_issues}")


def generate_markdown_report(report: AuditReport) -> str:
    """Generate a markdown report from the audit results."""
    lines = [
        "# Comprehensive Project Audit Report",
        f"**JackSparrow Trading Agent**",
        "",
        f"**Date**: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Execution Time**: {report.execution_time:.2f} seconds",
        f"**Overall Health Score**: {report.overall_health_score:.1f}/100",
        "",
        "## Executive Summary",
        "",
        f"- **Total Checks**: {report.total_checks}",
        f"- **Passed**: {report.passed_checks}",
        f"- **Failed**: {report.failed_checks}",
        f"- **Critical Issues**: {report.critical_issues}",
        f"- **High Priority Issues**: {report.high_issues}",
        "",
    ]

    # Category summaries
    lines.extend([
        "## Category Summary",
        "",
        "| Category | Checks | Pass Rate | Critical | High | Status |",
        "|----------|--------|-----------|----------|------|--------|",
    ])

    for category_name, category in report.categories.items():
        status = "[PASS]" if category.pass_rate >= 80 else "[WARN]" if category.pass_rate >= 60 else "[FAIL]"
        lines.append(
            f"| {category_name.replace('_', ' ').title()} | {len(category.checks)} | {category.pass_rate:.1f}% | {category.critical_failures} | {category.high_failures} | {status} |"
        )

    lines.append("")

    # Detailed findings
    lines.extend([
        "## Detailed Findings",
        "",
    ])

    for category_name, category in report.categories.items():
        lines.extend([
            f"### {category_name.replace('_', ' ').title()}",
            "",
        ])

        for check in category.checks:
            status_emoji = {
                'pass': '[PASS]',
                'fail': '[FAIL]',
                'warning': '[WARN]',
                'error': '[ERROR]',
                'skip': '[SKIP]'
            }.get(check.status, '[UNKNOWN]')

            lines.extend([
                f"#### {status_emoji} {check.check_name}",
                "",
                f"**Severity**: {check.severity.title()}",
                f"**Status**: {check.status.title()}",
                f"**Duration**: {check.duration:.2f}s",
                "",
                check.message,
                "",
            ])

            if check.details:
                lines.extend([
                    "**Details:**",
                    "```",
                    check.details,
                    "```",
                    "",
                ])

            if check.recommendations:
                lines.extend([
                    "**Recommendations:**",
                ])
                for rec in check.recommendations:
                    lines.append(f"- {rec}")
                lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())