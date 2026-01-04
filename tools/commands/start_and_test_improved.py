#!/usr/bin/env python3
"""
Improved Orchestrated System Startup and Continuous Test Execution

Enhanced version of start_and_test.py with:
- Better error handling and logging
- Cleaner separation of concerns
- Improved configuration management
- More robust async patterns
- Better test coordination
"""

import os
import sys
import asyncio
import argparse
import signal
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

# Import improved utilities and components
from tools.commands.start_parallel_improved import (
    ParallelProcessManager, setup_services, ensure_dependencies,
    load_root_env, get_npm_executable, check_prerequisites,
    attempt_start_redis, Colors, PaperTradingValidator
)
from tools.commands.test_logger import TestLogger, LogLevel, LogCategory
from tests.functionality.test_coordinator import TestCoordinator
from tests.functionality.report_generator import ReportGenerator
from tests.functionality.config import config as test_config
from tests.functionality.fixtures import cleanup_shared_resources
from tests.functionality.utils import TestSuiteResult, TestStatus


class OrchestrationError(Exception):
    """Base exception for orchestration errors."""

    def __init__(self, message: str, service: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        """Initialize orchestration error.

        Args:
            message: Error message
            service: Service name if error is service-specific
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.service = service
        self.details = details or {}


class ServiceStartupError(OrchestrationError):
    """Service startup failed."""

    def __init__(self, service: str, reason: str, details: Optional[Dict[str, Any]] = None):
        """Initialize service startup error.

        Args:
            service: Service name that failed to start
            reason: Reason for failure
            details: Additional error details
        """
        message = f"Service '{service}' failed to start: {reason}"
        super().__init__(message, service=service, details=details)
        self.reason = reason


class HealthCheckError(OrchestrationError):
    """Health check failed."""

    def __init__(self, service: str, reason: str, details: Optional[Dict[str, Any]] = None):
        """Initialize health check error.

        Args:
            service: Service name that failed health check
            reason: Reason for failure
            details: Additional error details
        """
        message = f"Service '{service}' failed health check: {reason}"
        super().__init__(message, service=service, details=details)
        self.reason = reason


class TestExecutionError(OrchestrationError):
    """Test execution failed."""

    def __init__(self, message: str, test_group: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        """Initialize test execution error.

        Args:
            message: Error message
            test_group: Test group name if error is group-specific
            details: Additional error details
        """
        super().__init__(message, details=details)
        self.test_group = test_group


class CriticalFailureError(OrchestrationError):
    """Critical test failure detected - system should terminate."""

    def __init__(self, message: str, failed_tests: List[Dict[str, Any]],
                 details: Optional[Dict[str, Any]] = None):
        """Initialize critical failure error.

        Args:
            message: Error message
            failed_tests: List of failed test details
            details: Additional error details
        """
        super().__init__(message, details=details)
        self.failed_tests = failed_tests


@dataclass
class OrchestrationConfig:
    """Configuration for orchestration execution.

    Attributes:
        timeout: Health check timeout in seconds
        retry_interval: Health check retry interval in seconds
        max_workers: Maximum parallel test workers
        cleanup_timeout: Cleanup operation timeout in seconds
        shutdown_timeout: Graceful shutdown timeout in seconds
        skip_startup: Whether to skip service startup
        test_mode: Test execution mode (grouped, parallel, sequential)
        verbose: Enable verbose logging
        test_groups: Specific test groups to run (None = all)
        continuous_mode: Enable continuous testing mode
        test_interval: Interval between test cycles in seconds
        terminate_on_failure: Terminate on any test failure
        keep_services_running: Keep services running after tests complete
    """
    timeout: float = 60.0
    retry_interval: float = 2.0
    max_workers: int = 4
    cleanup_timeout: float = 30.0
    shutdown_timeout: float = 10.0
    skip_startup: bool = False
    test_mode: str = "grouped"
    verbose: bool = False
    test_groups: Optional[List[str]] = None
    continuous_mode: bool = True
    test_interval: float = 300.0
    terminate_on_failure: bool = True
    keep_services_running: bool = True

    def __post_init__(self):
        """Validate configuration values."""
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.retry_interval <= 0:
            raise ValueError(f"retry_interval must be positive, got {self.retry_interval}")
        if self.max_workers <= 0:
            raise ValueError(f"max_workers must be positive, got {self.max_workers}")
        if self.cleanup_timeout <= 0:
            raise ValueError(f"cleanup_timeout must be positive, got {self.cleanup_timeout}")
        if self.shutdown_timeout <= 0:
            raise ValueError(f"shutdown_timeout must be positive, got {self.shutdown_timeout}")
        if self.test_mode not in ("grouped", "parallel", "sequential"):
            raise ValueError(f"test_mode must be one of: grouped, parallel, sequential, got {self.test_mode}")
        if self.test_interval <= 0:
            raise ValueError(f"test_interval must be positive, got {self.test_interval}")


class FailureAnalyzer:
    """Analyzes test results for critical failures.

    Attributes:
        logger: Test logger instance
        terminate_on_failure: Whether to terminate on any failure
    """

    def __init__(self, logger: TestLogger, terminate_on_failure: bool = True):
        """Initialize failure analyzer.

        Args:
            logger: Test logger instance
            terminate_on_failure: Whether to terminate on any failure
        """
        self.logger = logger
        self.terminate_on_failure = terminate_on_failure

    def analyze_results(self, all_results: Dict[str, List[TestSuiteResult]]) -> Optional[CriticalFailureError]:
        """Analyze test results for critical failures.

        Args:
            all_results: Dictionary mapping test group names to their results

        Returns:
            CriticalFailureError if critical failure detected, None otherwise
        """
        failed_tests = []

        for group_name, results in all_results.items():
            for suite_result in results:
                # Check suite-level status
                if suite_result.status == TestStatus.FAIL:
                    failed_tests.append({
                        "group": group_name,
                        "suite": suite_result.suite_name,
                        "status": suite_result.status.value,
                        "issues": suite_result.issues,
                        "error": None
                    })

                # Check individual test results
                for test_result in suite_result.results:
                    if test_result.status == TestStatus.FAIL:
                        failed_tests.append({
                            "group": group_name,
                            "suite": suite_result.suite_name,
                            "test": test_result.name,
                            "status": test_result.status.value,
                            "issues": test_result.issues,
                            "error": test_result.error
                        })

        if failed_tests and self.terminate_on_failure:
            error_msg = f"Critical failure detected: {len(failed_tests)} test(s) failed"
            self.logger.error(
                LogCategory.TEST,
                error_msg,
                details={
                    "failed_count": len(failed_tests),
                    "failed_tests": failed_tests[:10]  # Limit to first 10 for logging
                }
            )
            return CriticalFailureError(
                message=error_msg,
                failed_tests=failed_tests,
                details={"failed_count": len(failed_tests)}
            )

        return None


class ContinuousTestRunner:
    """Manages continuous test execution cycles.

    Attributes:
        test_executor: Test executor instance
        failure_analyzer: Failure analyzer instance
        logger: Test logger instance
        config: Orchestration configuration
        cycle_count: Current cycle number
        cumulative_stats: Cumulative statistics across cycles
    """

    def __init__(self, test_executor: "TestExecutor", failure_analyzer: FailureAnalyzer,
                 logger: TestLogger, config: OrchestrationConfig):
        """Initialize continuous test runner.

        Args:
            test_executor: Test executor instance
            failure_analyzer: Failure analyzer instance
            logger: Test logger instance
            config: Orchestration configuration
        """
        self.test_executor = test_executor
        self.failure_analyzer = failure_analyzer
        self.logger = logger
        self.config = config
        self.cycle_count = 0
        self.last_coordinator: Optional[TestCoordinator] = None
        self.cumulative_stats = {
            "total_cycles": 0,
            "total_tests": 0,
            "total_passed": 0,
            "total_failed": 0,
            "total_warnings": 0,
            "start_time": datetime.now(timezone.utc)
        }

    async def run_cycle(self) -> Optional[CriticalFailureError]:
        """Run a single test cycle.

        Returns:
            CriticalFailureError if critical failure detected, None otherwise
        """
        self.cycle_count += 1
        cycle_start = datetime.now(timezone.utc)

        self.logger.info(
            LogCategory.TEST,
            f"Starting test cycle #{self.cycle_count}",
            details={
                "phase": "test-cycle",
                "cycle": self.cycle_count,
                "start_time": cycle_start.isoformat()
            }
        )

        print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
        print(f"{Colors.BOLD}Test Cycle #{self.cycle_count}{Colors.RESET}")
        print(f"{Colors.BOLD}Started at: {cycle_start.strftime('%Y-%m-%d %H:%M:%S UTC')}{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")

        try:
            # Run tests
            all_results, coordinator = await self.test_executor.run_tests()

            # Store coordinator for final summary
            self.last_coordinator = coordinator

            # Get summary from the coordinator that actually ran the tests
            summary = coordinator.get_summary()

            # Update cumulative stats
            self.cumulative_stats["total_cycles"] = self.cycle_count
            self.cumulative_stats["total_tests"] += summary.get("total_tests", 0)
            self.cumulative_stats["total_passed"] += summary.get("passed", 0)
            self.cumulative_stats["total_failed"] += summary.get("failed", 0)
            self.cumulative_stats["total_warnings"] += summary.get("warnings", 0)

            cycle_end = datetime.now(timezone.utc)
            cycle_duration = (cycle_end - cycle_start).total_seconds()

            # Log cycle summary
            self.logger.info(
                LogCategory.TEST,
                f"Test cycle #{self.cycle_count} completed",
                details={
                    "phase": "test-cycle",
                    "cycle": self.cycle_count,
                    "duration_seconds": cycle_duration,
                    "passed": summary.get("passed", 0),
                    "failed": summary.get("failed", 0),
                    "warnings": summary.get("warnings", 0),
                    "end_time": cycle_end.isoformat()
                }
            )

            # Print cycle summary
            print(f"\n{Colors.BOLD}Cycle #{self.cycle_count} Summary{Colors.RESET}")
            print(f"Duration: {cycle_duration:.2f}s")
            print(f"Passed: {Colors.GREEN}{summary.get('passed', 0)}{Colors.RESET}")
            if summary.get('failed', 0) > 0:
                print(f"Failed: {Colors.ERROR}{summary.get('failed', 0)}{Colors.RESET}")
            else:
                print(f"Failed: {summary.get('failed', 0)}")
            if summary.get('warnings', 0) > 0:
                print(f"Warnings: {Colors.YELLOW}{summary.get('warnings', 0)}{Colors.RESET}")
            else:
                print(f"Warnings: {summary.get('warnings', 0)}")

            # Print cumulative stats
            print(f"\n{Colors.BOLD}Cumulative Statistics{Colors.RESET}")
            print(f"Total Cycles: {self.cumulative_stats['total_cycles']}")
            print(f"Total Tests: {self.cumulative_stats['total_tests']}")
            print(f"Total Passed: {Colors.GREEN}{self.cumulative_stats['total_passed']}{Colors.RESET}")
            if self.cumulative_stats['total_failed'] > 0:
                print(f"Total Failed: {Colors.ERROR}{self.cumulative_stats['total_failed']}{Colors.RESET}")
            else:
                print(f"Total Failed: {self.cumulative_stats['total_failed']}")
            if self.cumulative_stats['total_warnings'] > 0:
                print(f"Total Warnings: {Colors.YELLOW}{self.cumulative_stats['total_warnings']}{Colors.RESET}")
            else:
                print(f"Total Warnings: {self.cumulative_stats['total_warnings']}")

            # Analyze for critical failures
            critical_error = self.failure_analyzer.analyze_results(all_results)

            if critical_error:
                print(f"\n{Colors.ERROR}{'='*80}{Colors.RESET}")
                print(f"{Colors.ERROR}CRITICAL FAILURE DETECTED{Colors.RESET}")
                print(f"{Colors.ERROR}{'='*80}{Colors.RESET}")
                print(f"{Colors.ERROR}Failed Tests: {len(critical_error.failed_tests)}{Colors.RESET}")
                for failed_test in critical_error.failed_tests[:5]:
                    test_name = failed_test.get("test") or failed_test.get("suite", "unknown")
                    print(f"{Colors.ERROR}  - {failed_test.get('group', 'unknown')}/{test_name}{Colors.RESET}")
                print(f"{Colors.ERROR}{'='*80}{Colors.RESET}\n")

            return critical_error

        except Exception as e:
            error_msg = f"Error during test cycle #{self.cycle_count}: {str(e)}"
            self.logger.error(
                LogCategory.TEST,
                error_msg,
                error=str(e),
                details={"phase": "test-cycle", "cycle": self.cycle_count}
            )
            # If terminate_on_failure is enabled, treat execution errors as critical
            if self.config.terminate_on_failure:
                return CriticalFailureError(
                    message=error_msg,
                    failed_tests=[],
                    details={"error": str(e), "type": type(e).__name__, "cycle": self.cycle_count}
                )
            return None

    def get_cumulative_stats(self) -> Dict[str, Any]:
        """Get cumulative statistics.

        Returns:
            Dictionary with cumulative statistics
        """
        return self.cumulative_stats.copy()


class ServiceOrchestrator:
    """Manages service lifecycle: startup, health checks, and shutdown.

    Attributes:
        project_root: Project root directory
        logger: Test logger instance
        config: Orchestration configuration
        manager: Parallel process manager instance
        services_status: Dictionary mapping service names to health status
    """

    def __init__(self, project_root: Path, logger: TestLogger, config: OrchestrationConfig):
        """Initialize service orchestrator.

        Args:
            project_root: Project root directory
            logger: Test logger instance
            config: Orchestration configuration
        """
        self.project_root = project_root
        self.logger = logger
        self.config = config
        self.manager: Optional[ParallelProcessManager] = None
        self.services_status: Dict[str, bool] = {}

    def start_services(self) -> bool:
        """Start all system services.

        Returns:
            True if all services started successfully, False otherwise

        Raises:
            ServiceStartupError: If service startup fails
        """
        self.logger.info(
            LogCategory.STARTUP,
            "Starting system services...",
            details={"phase": "startup"}
        )

        try:
            npm_cmd = get_npm_executable()
        except FileNotFoundError as e:
            error_msg = f"npm executable not found: {e}"
            self.logger.error(LogCategory.STARTUP, error_msg, error=str(e))
            raise ServiceStartupError(
                service="npm",
                reason=error_msg,
                details={"error": str(e)}
            ) from e

        try:
            # Setup services
            self.manager = setup_services(self.project_root, npm_cmd)

            # Store paper validator reference if available
            from tools.commands.start_parallel_improved import PaperTradingValidator
            paper_validator = PaperTradingValidator(self.project_root)
            self.manager.paper_validator = paper_validator

            # Start all services
            if not self.manager.start_all():
                error_msg = "Failed to start all services"
                self.logger.error(LogCategory.STARTUP, error_msg)
                raise ServiceStartupError(
                    service="all",
                    reason=error_msg,
                    details={"services": list(self.manager.services.keys()) if self.manager else []}
                )

            self.logger.info(LogCategory.STARTUP, "All services started successfully")
            return True

        except ServiceStartupError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error during service startup: {str(e)}"
            self.logger.error(LogCategory.STARTUP, error_msg, error=str(e))
            raise ServiceStartupError(
                service="unknown",
                reason=error_msg,
                details={"error": str(e), "type": type(e).__name__}
            ) from e

    def wait_for_health(self) -> Dict[str, bool]:
        """Wait for all services to become healthy.

        Returns:
            Dictionary mapping service names to health status

        Raises:
            HealthCheckError: If critical services fail health checks
        """
        if not self.manager:
            # If skipping startup, assume all services are ready
            self.services_status = {
                "Backend": True,
                "Feature Server": True,
                "Frontend": True,
                "Database": True,
                "Redis": True,
                "WebSocket": True
            }
            self.logger.info(
                LogCategory.HEALTH,
                "Skipping health checks (startup skipped)",
                details={"phase": "health-check"}
            )
            return self.services_status

        self.logger.info(
            LogCategory.HEALTH,
            "Waiting for services to become ready...",
            details={"phase": "health-check", "timeout": self.config.timeout}
        )

        try:
            self.services_status = self.manager.wait_for_services_ready(
                timeout=self.config.timeout,
                retry_interval=self.config.retry_interval
            )

            failed_services = [
                name for name, ready in self.services_status.items() if not ready
            ]

            if failed_services:
                warning_msg = f"Some services are not ready: {', '.join(failed_services)}"
                self.logger.error(
                    LogCategory.HEALTH,
                    warning_msg,
                    details={"failed_services": failed_services, "phase": "health-check"}
                )
                # Continue anyway - tests may still be able to run
                # Only raise if critical services failed
                critical_services = ["Backend", "Database", "Redis"]
                critical_failed = [s for s in failed_services if s in critical_services]
                if critical_failed:
                    raise HealthCheckError(
                        service=", ".join(critical_failed),
                        reason=warning_msg,
                        details={"failed_services": failed_services, "critical_failed": critical_failed}
                    )
            else:
                self.logger.info(
                    LogCategory.HEALTH,
                    "All services are ready",
                    details={"phase": "health-check"}
                )

            return self.services_status

        except HealthCheckError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error during health checks: {str(e)}"
            self.logger.error(LogCategory.HEALTH, error_msg, error=str(e))
            raise HealthCheckError(
                service="unknown",
                reason=error_msg,
                details={"error": str(e), "type": type(e).__name__}
            ) from e

    async def monitor_services(self, shutdown_event: asyncio.Event) -> Optional[str]:
        """Monitor services for crashes (runs in background).

        Args:
            shutdown_event: Event to signal shutdown

        Returns:
            Name of crashed service if detected, None otherwise
        """
        if not self.manager:
            return None

        critical_services = ["Backend", "Database", "Redis"]
        check_interval = 60.0  # Check every minute

        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(check_interval)

                if not self.manager:
                    break

                # Check if any critical service died
                for name, manager in self.manager.services.items():
                    if name in critical_services and manager.running and not manager.is_alive():
                        error_msg = f"Critical service '{name}' crashed unexpectedly"
                        self.logger.error(
                            LogCategory.HEALTH,
                            error_msg,
                            service=name,
                            details={
                                "phase": "service-monitoring",
                                "recent_errors": manager.recent_errors[:3] if manager.recent_errors else []
                            }
                        )
                        return name

                # Update service status
                current_status = {}
                for name, manager in self.manager.services.items():
                    current_status[name] = manager.is_alive() if manager.running else False

                # Log status changes
                for name, is_alive in current_status.items():
                    previous_status = self.services_status.get(name, None)
                    if previous_status != is_alive:
                        status_msg = "healthy" if is_alive else "unhealthy"
                        self.logger.info(
                            LogCategory.HEALTH,
                            f"Service '{name}' status changed: {status_msg}",
                            service=name,
                            details={"phase": "service-monitoring", "status": status_msg}
                        )

                self.services_status.update(current_status)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.warning(
                    LogCategory.HEALTH,
                    f"Error during service monitoring: {str(e)}",
                    error=str(e),
                    details={"phase": "service-monitoring"}
                )

        return None

    def shutdown_services(self) -> None:
        """Shutdown all services gracefully.

        Raises:
            OrchestrationError: If shutdown fails
        """
        if not self.manager:
            return

        self.logger.info(
            LogCategory.SYSTEM,
            "Stopping all services...",
            details={"phase": "shutdown"}
        )

        try:
            self.manager.stop_all()
            self.logger.info(
                LogCategory.SYSTEM,
                "All services stopped successfully",
                details={"phase": "shutdown"}
            )
        except Exception as e:
            error_msg = f"Error during service shutdown: {str(e)}"
            self.logger.warning(LogCategory.SYSTEM, error_msg, error=str(e))
            # Don't raise - cleanup should continue even if shutdown fails


class TestExecutor:
    """Manages test execution and report generation.

    Attributes:
        logger: Test logger instance
        config: Orchestration configuration
        services_status: Dictionary mapping service names to health status
        cycle_count: Current test cycle count
    """

    def __init__(self, logger: TestLogger, config: OrchestrationConfig,
                 services_status: Dict[str, bool]):
        """Initialize test executor.

        Args:
            logger: Test logger instance
            config: Orchestration configuration
            services_status: Dictionary mapping service names to health status
        """
        self.logger = logger
        self.config = config
        self.services_status = services_status
        self.cycle_count = 0

    async def run_tests(self) -> Tuple[Dict[str, List[TestSuiteResult]], TestCoordinator]:
        """Run functionality tests.

        Returns:
            Tuple of (results_dict, coordinator) where:
            - results_dict: Dictionary mapping test group names to their results
            - coordinator: The TestCoordinator instance that ran the tests

        Raises:
            TestExecutionError: If test execution fails
        """
        self.logger.info(
            LogCategory.TEST,
            "Starting test execution...",
            details={"phase": "test-execution", "mode": self.config.test_mode}
        )

        # Update test config
        test_config.verbose = self.config.verbose
        test_config.max_workers = self.config.max_workers

        # Determine execution mode
        if self.config.test_mode == "sequential":
            parallel = False
            grouped = False
        elif self.config.test_mode == "parallel":
            parallel = True
            grouped = False
        else:  # grouped (default)
            parallel = True
            grouped = True

        self.logger.info(
            LogCategory.TEST,
            f"Test execution mode: {self.config.test_mode} (parallel={parallel}, grouped={grouped})",
            details={"phase": "test-execution", "parallel": parallel, "grouped": grouped}
        )

        # Initialize coordinator
        coordinator = TestCoordinator(max_workers=self.config.max_workers)

        try:
            # Run tests
            if self.config.test_groups:
                self.logger.info(
                    LogCategory.TEST,
                    f"Running specific test groups: {', '.join(self.config.test_groups)}",
                    details={"phase": "test-execution", "groups": self.config.test_groups}
                )
                all_results = await coordinator.run_specific_groups(
                    self.config.test_groups,
                    parallel=parallel
                )
            else:
                all_results = await coordinator.run_all_groups(
                    parallel=parallel,
                    grouped=grouped
                )

            return all_results, coordinator

        except Exception as e:
            error_msg = f"Error during test execution: {str(e)}"
            self.logger.error(
                LogCategory.TEST,
                error_msg,
                error=str(e),
                details={"phase": "test-execution"}
            )
            raise TestExecutionError(
                message=error_msg,
                details={"error": str(e), "type": type(e).__name__}
            ) from e

    def generate_reports(self, all_results: Dict[str, List[TestSuiteResult]]) -> Dict[str, Path]:
        """Generate test reports.

        Args:
            all_results: Dictionary mapping test group names to their results

        Returns:
            Dictionary mapping report format names to file paths
        """
        self.logger.info(
            LogCategory.TEST,
            "Generating test reports...",
            details={"phase": "report-generation"}
        )

        generator = ReportGenerator()

        # Add startup info to report
        startup_errors = [
            {
                "service": entry.service or "unknown",
                "message": entry.message,
                "error": entry.error,
                "solution": "Check service logs and configuration"
            }
            for entry in self.logger.get_startup_errors()
        ]
        startup_warnings = [
            {
                "service": entry.service or "unknown",
                "message": entry.message,
                "solution": "Review service configuration"
            }
            for entry in self.logger.get_startup_warnings()
        ]

        generator.add_startup_info(
            self.services_status,
            startup_errors=startup_errors,
            startup_warnings=startup_warnings
        )

        # Add test results
        for group_name, results in all_results.items():
            generator.add_results(group_name, results)

        # Generate reports
        reports = generator.generate_all_reports()

        self.logger.info(
            LogCategory.TEST,
            f"Reports generated: {', '.join(reports.keys())}",
            details={"phase": "report-generation", "reports": list(reports.keys())}
        )

        return reports


class OrchestratedTestRunner:
    """Orchestrates system startup and test execution.

    This class coordinates the complete lifecycle: service startup, health checks,
    test execution, and cleanup. It implements async context manager protocol
    for proper resource management.

    Attributes:
        project_root: Project root directory
        logger: Test logger instance
        config: Orchestration configuration
        service_orchestrator: Service lifecycle manager
        test_executor: Test execution manager
        session_id: Unique session identifier for tracking
        shutdown_event: Flag indicating shutdown was requested
    """

    def __init__(self, project_root: Path, logger: TestLogger, config: OrchestrationConfig):
        """Initialize orchestrated test runner.

        Args:
            project_root: Project root directory
            logger: Test logger instance
            config: Orchestration configuration
        """
        self.project_root = project_root
        self.logger = logger
        self.config = config
        self.service_orchestrator: Optional[ServiceOrchestrator] = None
        self.test_executor: Optional[TestExecutor] = None
        self.session_id = str(uuid.uuid4())
        self.shutdown_event = False
        self._cleanup_completed = False
        self._continuous_mode_active = False

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals.

        Args:
            signum: Signal number
            frame: Current stack frame
        """
        if not self.shutdown_event:
            self.logger.info(
                LogCategory.SYSTEM,
                "Shutdown signal received, cleaning up...",
                details={"phase": "shutdown", "signal": signum, "session_id": self.session_id}
            )
            self.shutdown_event = True

    @asynccontextmanager
    async def managed_execution(self):
        """Context manager for managed execution with proper cleanup."""
        try:
            yield self
        finally:
            await self._async_cleanup()

    async def __aenter__(self) -> "OrchestratedTestRunner":
        """Enter async context manager.

        Returns:
            Self instance
        """
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[Exception],
                       exc_tb: Optional[Any]) -> bool:
        """Exit async context manager with cleanup.

        Args:
            exc_type: Exception type if exception occurred
            exc_val: Exception value if exception occurred
            exc_tb: Exception traceback if exception occurred

        Returns:
            False to not suppress exceptions
        """
        await self._async_cleanup()
        return False  # Don't suppress exceptions

    async def _run_single_mode(self) -> bool:
        """Run tests once and exit.

        Returns:
            True if all tests passed, False otherwise
        """
        try:
            # Run tests
            all_results, coordinator = await self.test_executor.run_tests()
        except TestExecutionError as e:
            self.logger.error(
                LogCategory.TEST,
                f"Test execution failed: {e.message}",
                error=str(e),
                details={"session_id": self.session_id, "phase": "test-execution"}
            )
            return False

        # Generate reports
        try:
            reports = self.test_executor.generate_reports(all_results)
        except Exception as e:
            self.logger.warning(
                LogCategory.TEST,
                f"Report generation failed: {str(e)}",
                error=str(e),
                details={"session_id": self.session_id, "phase": "report-generation"}
            )
            reports = {}

        # Get summary from the coordinator that actually ran the tests
        summary = coordinator.get_summary()

        self.logger.info(
            LogCategory.TEST,
            f"Test execution completed: {summary['passed']} passed, "
            f"{summary['failed']} failed, {summary['warnings']} warnings",
            details={
                "session_id": self.session_id,
                "phase": "test-execution",
                "summary": summary
            }
        )

        self._print_test_summary(summary, reports)

        # Log errors and warnings
        test_errors = self.logger.get_test_errors()
        test_warnings = self.logger.get_test_warnings()

        if test_errors:
            self.logger.error(
                LogCategory.TEST,
                f"Test execution completed with {len(test_errors)} errors",
                details={"session_id": self.session_id, "error_count": len(test_errors)}
            )
            for entry in test_errors[:5]:  # Log first 5 errors
                self.logger.error(
                    LogCategory.TEST,
                    entry.message,
                    service=entry.service,
                    error=entry.error,
                    details={"session_id": self.session_id}
                )

        if test_warnings:
            self.logger.warning(
                LogCategory.TEST,
                f"Test execution completed with {len(test_warnings)} warnings",
                details={"session_id": self.session_id, "warning_count": len(test_warnings)}
            )

        return summary['failed'] == 0

    async def _run_continuous_mode(self) -> bool:
        """Run tests continuously until shutdown or critical failure.

        Returns:
            True if shutdown gracefully, False if critical failure detected
        """
        self._continuous_mode_active = True
        shutdown_event = asyncio.Event()

        try:
            # Initialize failure analyzer and continuous runner
            failure_analyzer = FailureAnalyzer(
                self.logger,
                terminate_on_failure=self.config.terminate_on_failure
            )
            continuous_runner = ContinuousTestRunner(
                self.test_executor,
                failure_analyzer,
                self.logger,
                self.config
            )

            # Start service monitoring task
            if self.service_orchestrator.manager:
                monitor_task = asyncio.create_task(
                    self.service_orchestrator.monitor_services(shutdown_event)
                )

            self.logger.info(
                LogCategory.SYSTEM,
                f"Starting continuous test mode (interval: {self.config.test_interval}s)",
                details={
                    "session_id": self.session_id,
                    "phase": "continuous-mode",
                    "test_interval": self.config.test_interval,
                    "terminate_on_failure": self.config.terminate_on_failure
                }
            )

            print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
            print(f"{Colors.BOLD}Continuous Testing Mode{Colors.RESET}")
            print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
            print(f"Test Interval: {self.config.test_interval}s ({self.config.test_interval/60:.1f} minutes)")
            print(f"Terminate on Failure: {self.config.terminate_on_failure}")
            print(f"Press Ctrl+C to stop\n")

            # Continuous test loop
            while not self.shutdown_event and not shutdown_event.is_set():
                # Run test cycle
                critical_error = await continuous_runner.run_cycle()

                if critical_error:
                    # Critical failure detected - terminate
                    self.logger.error(
                        LogCategory.TEST,
                        f"Critical failure detected, terminating: {critical_error.message}",
                        error=str(critical_error),
                        details={
                            "session_id": self.session_id,
                            "phase": "critical-failure",
                            "failed_tests": critical_error.failed_tests[:10]
                        }
                    )
                    return False

                # Check if service monitoring detected a crash
                if monitor_task and monitor_task.done():
                    crashed_service = monitor_task.result()
                    if crashed_service:
                        error_msg = f"Critical service '{crashed_service}' crashed, terminating"
                        self.logger.error(
                            LogCategory.HEALTH,
                            error_msg,
                            service=crashed_service,
                            details={"session_id": self.session_id, "phase": "service-crash"}
                        )
                        return False

                # Wait for next cycle (or shutdown signal)
                if not self.shutdown_event and not shutdown_event.is_set():
                    try:
                        await asyncio.wait_for(
                            shutdown_event.wait(),
                            timeout=self.config.test_interval
                        )
                        # Shutdown signal received
                        break
                    except asyncio.TimeoutError:
                        # Timeout means continue to next cycle
                        pass

            # Shutdown requested
            self.logger.info(
                LogCategory.SYSTEM,
                "Continuous testing stopped",
                details={
                    "session_id": self.session_id,
                    "phase": "shutdown",
                    "cycles_completed": continuous_runner.cycle_count,
                    "cumulative_stats": continuous_runner.get_cumulative_stats()
                }
            )

            # Generate final reports
            try:
                # Use the last coordinator that ran tests for summary
                if self.last_coordinator:
                    summary = self.last_coordinator.get_summary()
                    # Get the last results for report generation
                    # Note: In a more complete implementation, we'd track all results across cycles
                    all_results = {}  # For now, use empty dict as before
                else:
                    # Fallback if no tests were run
                    summary = {
                        "total_tests": 0,
                        "passed": 0,
                        "failed": 0,
                        "warnings": 0,
                        "groups_completed": 0,
                        "groups": 0
                    }
                    all_results = {}

                reports = self.test_executor.generate_reports(all_results)

                # Print final summary
                cumulative_stats = continuous_runner.get_cumulative_stats()
                print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
                print(f"{Colors.BOLD}Final Summary{Colors.RESET}")
                print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
                print(f"Total Cycles: {cumulative_stats['total_cycles']}")
                print(f"Total Tests: {cumulative_stats['total_tests']}")
                print(f"Total Passed: {Colors.GREEN}{cumulative_stats['total_passed']}{Colors.RESET}")
                if cumulative_stats['total_failed'] > 0:
                    print(f"Total Failed: {Colors.ERROR}{cumulative_stats['total_failed']}{Colors.RESET}")
                else:
                    print(f"Total Failed: {cumulative_stats['total_failed']}")
                if cumulative_stats['total_warnings'] > 0:
                    print(f"Total Warnings: {Colors.YELLOW}{cumulative_stats['total_warnings']}{Colors.RESET}")
                else:
                    print(f"Total Warnings: {cumulative_stats['total_warnings']}")
                print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")

            except Exception as e:
                self.logger.warning(
                    LogCategory.TEST,
                    f"Final report generation failed: {str(e)}",
                    error=str(e),
                    details={"session_id": self.session_id, "phase": "report-generation"}
                )

            return True

        finally:
            # Cancel monitoring task
            if monitor_task and not monitor_task.done():
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

    async def run(self) -> bool:
        """Run the complete orchestration: startup -> health checks -> tests.

        In continuous mode, runs tests in a loop until shutdown or critical failure.
        In single-run mode, runs tests once and exits.

        Returns:
            True if all tests passed (or continuous mode running), False otherwise

        Raises:
            ServiceStartupError: If service startup fails
            HealthCheckError: If critical services fail health checks
            TestExecutionError: If test execution fails
            CriticalFailureError: If critical failure detected in continuous mode
        """
        try:
            # Initialize components
            self.service_orchestrator = ServiceOrchestrator(
                self.project_root,
                self.logger,
                self.config
            )

            # Step 1: Startup services (if not skipped)
            if not self.config.skip_startup:
                try:
                    self.service_orchestrator.start_services()
                except ServiceStartupError as e:
                    self.logger.error(
                        LogCategory.STARTUP,
                        f"Service startup failed: {e.message}",
                        service=e.service,
                        error=str(e),
                        details={"session_id": self.session_id, "phase": "startup"}
                    )
                    return False
            else:
                self.logger.info(
                    LogCategory.STARTUP,
                    "Skipping service startup (assume services already running)",
                    details={"session_id": self.session_id, "phase": "startup"}
                )

            # Step 2: Wait for services to be ready
            try:
                services_status = self.service_orchestrator.wait_for_health()
            except HealthCheckError as e:
                self.logger.error(
                    LogCategory.HEALTH,
                    f"Health check failed: {e.message}",
                    service=e.service,
                    error=str(e),
                    details={"session_id": self.session_id, "phase": "health-check"}
                )
                # Continue anyway - tests may still be able to run
                services_status = self.service_orchestrator.services_status

            # Step 3: Set frontend URL for tests if frontend port was dynamically assigned
            if self.service_orchestrator.manager and hasattr(self.service_orchestrator.manager, 'frontend_port'):
                frontend_port = self.service_orchestrator.manager.frontend_port
                if frontend_port != 3000:  # Only set if different from default
                    frontend_url = f"http://localhost:{frontend_port}"
                    os.environ["FRONTEND_URL"] = frontend_url
                    os.environ["TEST_FRONTEND_URL"] = frontend_url
                    # Update test config to use the correct URL
                    test_config.frontend_url = frontend_url
                    self.logger.info(
                        LogCategory.TEST,
                        f"Frontend running on port {frontend_port}, setting FRONTEND_URL={frontend_url}",
                        details={"phase": "test-execution", "frontend_port": frontend_port, "frontend_url": frontend_url}
                    )

            # Step 4: Initialize test executor
            self.test_executor = TestExecutor(
                self.logger,
                self.config,
                services_status
            )

            # Step 5: Run tests (continuous or single-run mode)
            if self.config.continuous_mode:
                return await self._run_continuous_mode()
            else:
                return await self._run_single_mode()

        except KeyboardInterrupt:
            self.logger.warning(
                LogCategory.SYSTEM,
                "Test execution interrupted by user",
                details={"session_id": self.session_id, "phase": "interrupted"}
            )
            return False
        except (ServiceStartupError, HealthCheckError, TestExecutionError, CriticalFailureError):
            # Already logged, re-raise
            raise
        except Exception as e:
            import traceback
            error_msg = f"Unexpected error during orchestration: {str(e)}"
            self.logger.error(
                LogCategory.SYSTEM,
                error_msg,
                error=str(e),
                details={
                    "session_id": self.session_id,
                    "traceback": traceback.format_exc(),
                    "type": type(e).__name__
                }
            )
            raise OrchestrationError(
                message=error_msg,
                details={"error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()}
            ) from e
        finally:
            # Cleanup shared resources (only if not keeping services running)
            if not self.config.keep_services_running:
                try:
                    await cleanup_shared_resources()
                except Exception as e:
                    self.logger.warning(
                        LogCategory.SYSTEM,
                        f"Error during shared resource cleanup: {str(e)}",
                        error=str(e),
                        details={"session_id": self.session_id, "phase": "cleanup"}
                    )

    def _print_test_summary(self, summary: Dict[str, Any], reports: Dict[str, Path]) -> None:
        """Print test execution summary.

        Args:
            summary: Test summary dictionary
            reports: Dictionary mapping report format names to file paths
        """
        print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
        print(f"{Colors.BOLD}Test Execution Summary{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {Colors.GREEN}{summary['passed']}{Colors.RESET}")
        if summary['failed'] > 0:
            print(f"Failed: {Colors.ERROR}{summary['failed']}{Colors.RESET}")
        else:
            print(f"Failed: {summary['failed']}")
        if summary['warnings'] > 0:
            print(f"Warnings: {Colors.YELLOW}{summary['warnings']}{Colors.RESET}")
        else:
            print(f"Warnings: {summary['warnings']}")
        print(f"Groups Completed: {summary['groups_completed']}/{summary['groups']}")

        if reports:
            print(f"\nReports generated:")
            for format_name, path in reports.items():
                print(f"  {format_name.upper()}: {path}")
        print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")

    async def _async_cleanup(self) -> None:
        """Perform async cleanup operations."""
        if self._cleanup_completed:
            return

        self._cleanup_completed = True

        try:
            # Cleanup with timeout
            await asyncio.wait_for(
                self._perform_cleanup(),
                timeout=self.config.cleanup_timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                LogCategory.SYSTEM,
                f"Cleanup timed out after {self.config.cleanup_timeout}s",
                details={"session_id": self.session_id, "phase": "cleanup"}
            )
        except Exception as e:
            self.logger.warning(
                LogCategory.SYSTEM,
                f"Error during cleanup: {str(e)}",
                error=str(e),
                details={"session_id": self.session_id, "phase": "cleanup"}
            )

    async def _perform_cleanup(self) -> None:
        """Perform actual cleanup operations."""
        # Step 1: Shutdown services
        # In continuous mode, always shutdown on exit
        # In single-run mode, only shutdown if keep_services_running is False
        should_shutdown = self._continuous_mode_active or not self.config.keep_services_running

        if self.service_orchestrator and should_shutdown:
            try:
                self.service_orchestrator.shutdown_services()
            except Exception as e:
                self.logger.warning(
                    LogCategory.SYSTEM,
                    f"Error shutting down services: {str(e)}",
                    error=str(e),
                    details={"session_id": self.session_id, "phase": "cleanup"}
                )

        # Step 2: Export logs
        try:
            log_file = self.logger.export_json()
            self.logger.info(
                LogCategory.SYSTEM,
                f"Logs exported to: {log_file}",
                details={"session_id": self.session_id, "phase": "cleanup", "log_file": str(log_file)}
            )
        except Exception as e:
            self.logger.warning(
                LogCategory.SYSTEM,
                f"Error exporting logs: {str(e)}",
                error=str(e),
                details={"session_id": self.session_id, "phase": "cleanup"}
            )

    def cleanup(self) -> None:
        """Synchronous cleanup (for backward compatibility).

        Note: Prefer using async context manager or _async_cleanup().
        """
        if not self._cleanup_completed:
            try:
                asyncio.run(self._async_cleanup())
            except RuntimeError:
                # Event loop already running, schedule cleanup
                asyncio.create_task(self._async_cleanup())


def _validate_test_groups(test_groups: List[str], logger: TestLogger) -> List[str]:
    """Validate test group names against available groups.

    Args:
        test_groups: List of test group names to validate
        logger: Logger instance for error reporting

    Returns:
        Validated list of test group names

    Raises:
        ValueError: If any test group name is invalid
    """
    available_groups = set(test_config.test_groups.keys())
    invalid_groups = [g for g in test_groups if g not in available_groups]

    if invalid_groups:
        error_msg = (
            f"Invalid test group(s): {', '.join(invalid_groups)}. "
            f"Available groups: {', '.join(sorted(available_groups))}"
        )
        logger.error(LogCategory.SYSTEM, error_msg)
        raise ValueError(error_msg)

    return test_groups


async def main():
    """Main entry point.

    Parses command-line arguments, validates inputs, sets up logging,
    and runs the orchestrated test execution.
    """
    parser = argparse.ArgumentParser(
        description="Start JackSparrow system and run comprehensive functionality tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run continuous testing (default - runs tests every 5 minutes)
  python tools/commands/start_and_test_improved.py

  # Run tests once and exit
  python tools/commands/start_and_test_improved.py --no-continuous

  # Skip startup (assume services already running)
  python tools/commands/start_and_test_improved.py --no-startup

  # Run specific test groups with custom interval
  python tools/commands/start_and_test_improved.py --groups infrastructure,core-services --test-interval 60

  # Run tests in parallel mode with verbose output
  python tools/commands/start_and_test_improved.py --test-mode parallel --verbose

  # Continue running even on failures (for debugging)
  python tools/commands/start_and_test_improved.py --no-terminate-on-failure
        """
    )
    parser.add_argument(
        "--no-startup",
        action="store_true",
        help="Skip system startup (assume services already running)"
    )
    parser.add_argument(
        "--test-mode",
        choices=["grouped", "parallel", "sequential"],
        default="grouped",
        help="Test execution mode (default: grouped)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Health check timeout in seconds (default: 60)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--groups",
        type=str,
        help="Comma-separated list of test groups to run"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum parallel test workers (default: 4)"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        default=True,
        help="Enable continuous testing mode (default: True)"
    )
    parser.add_argument(
        "--no-continuous",
        dest="continuous",
        action="store_false",
        help="Disable continuous testing mode (run tests once and exit)"
    )
    parser.add_argument(
        "--test-interval",
        type=float,
        default=300.0,
        help="Interval between test cycles in seconds (default: 300 = 5 minutes)"
    )
    parser.add_argument(
        "--no-terminate-on-failure",
        dest="terminate_on_failure",
        action="store_false",
        default=True,
        help="Continue running even on test failures (for debugging)"
    )
    parser.add_argument(
        "--websocket-monitor",
        action="store_true",
        help="Enable WebSocket connection monitoring and performance metrics"
    )

    args = parser.parse_args()

    # Validate inputs
    if args.timeout <= 0:
        print(f"Error: timeout must be positive, got {args.timeout}", file=sys.stderr)
        sys.exit(1)

    if args.max_workers <= 0:
        print(f"Error: max-workers must be positive, got {args.max_workers}", file=sys.stderr)
        sys.exit(1)

    if args.test_interval <= 0:
        print(f"Error: test-interval must be positive, got {args.test_interval}", file=sys.stderr)
        sys.exit(1)

    # Change to project root
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent.parent
    os.chdir(str(project_root))

    # Setup logging
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    logger = TestLogger(logs_dir, verbose=args.verbose)

    # Startup banner
    print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}JackSparrow Trading Agent - Orchestrated Startup and Testing{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"Started at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    # Load environment
    logger.info(
        LogCategory.STARTUP,
        "Loading environment configuration...",
        details={"phase": "startup"}
    )
    load_root_env(project_root)

    # Parse and validate test groups
    test_groups = None
    if args.groups:
        test_groups = [g.strip() for g in args.groups.split(",") if g.strip()]
        if test_groups:
            try:
                test_groups = _validate_test_groups(test_groups, logger)
            except ValueError:
                sys.exit(1)

    # Create configuration
    try:
        config = OrchestrationConfig(
            timeout=args.timeout,
            retry_interval=test_config.health_check_retry_interval,
            max_workers=args.max_workers,
            skip_startup=args.no_startup,
            test_mode=args.test_mode,
            verbose=args.verbose,
            test_groups=test_groups,
            continuous_mode=args.continuous,
            test_interval=args.test_interval,
            terminate_on_failure=getattr(args, 'terminate_on_failure', True),
            keep_services_running=args.continuous  # Keep services running in continuous mode
        )
    except ValueError as e:
        logger.error(LogCategory.SYSTEM, f"Invalid configuration: {e}", error=str(e))
        sys.exit(1)

    # Check prerequisites (only if starting services)
    if not config.skip_startup:
        # Attempt to start Redis if needed (before prerequisites check)
        logger.info(
            LogCategory.STARTUP,
            "Checking Redis availability...",
            details={"phase": "startup"}
        )
        attempt_start_redis(project_root)

        logger.info(
            LogCategory.STARTUP,
            "Checking prerequisites...",
            details={"phase": "startup"}
        )
        if not check_prerequisites():
            logger.error(
                LogCategory.STARTUP,
                "Prerequisites check failed - some required services are not available",
                details={"phase": "startup"}
            )
            logger.info(
                LogCategory.STARTUP,
                "You can try running with --no-startup if services are already running",
                details={"phase": "startup"}
            )
            sys.exit(1)

        # Ensure dependencies
        logger.info(
            LogCategory.STARTUP,
            "Ensuring dependencies are installed...",
            details={"phase": "startup"}
        )
        try:
            npm_cmd = get_npm_executable()
            ensure_dependencies(project_root, npm_cmd)
        except FileNotFoundError as e:
            logger.error(
                LogCategory.STARTUP,
                f"Dependency check failed: {e}",
                error=str(e),
                details={"phase": "startup"}
            )
            sys.exit(1)

    # Create and run orchestrator using async context manager
    try:
        async with OrchestratedTestRunner(project_root, logger, config) as orchestrator:
            success = await orchestrator.run()
    except (ServiceStartupError, HealthCheckError, TestExecutionError, CriticalFailureError, OrchestrationError) as e:
        logger.error(
            LogCategory.SYSTEM,
            f"Orchestration failed: {e.message}",
            service=getattr(e, 'service', None),
            error=str(e),
            details={"type": type(e).__name__}
        )
        success = False
    except KeyboardInterrupt:
        logger.warning(LogCategory.SYSTEM, "Orchestration interrupted by user")
        success = False
    except Exception as e:
        import traceback
        logger.error(
            LogCategory.SYSTEM,
            f"Unexpected error: {str(e)}",
            error=str(e),
            details={"traceback": traceback.format_exc(), "type": type(e).__name__}
        )
        success = False

    # Print final summary
    summary = logger.get_summary()
    print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}Orchestration Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"Startup Errors: {summary['startup_errors']}")
    print(f"Startup Warnings: {summary['startup_warnings']}")
    print(f"Test Errors: {summary['test_errors']}")
    print(f"Test Warnings: {summary['test_warnings']}")
    print(f"Health Issues: {summary['health_issues']}")
    print(f"Total Errors: {summary['total_errors']}")
    print(f"Total Warnings: {summary['total_warnings']}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")

    # Export logs (if not already exported)
    try:
        log_file = logger.export_json()
        print(f"Detailed logs exported to: {log_file}\n")
    except Exception as e:
        logger.warning(LogCategory.SYSTEM, f"Failed to export logs: {str(e)}", error=str(e))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
