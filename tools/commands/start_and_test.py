#!/usr/bin/env python3
"""
Orchestrated System Startup and Test Execution

Starts the JackSparrow trading agent system and runs comprehensive functionality tests.
Waits for services to be healthy before starting tests and provides comprehensive logging.
"""

import os
import sys
import asyncio
import argparse
import signal
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# Add project root to path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import startup components
from tools.commands.start_parallel import (
    ParallelProcessManager,
    setup_services,
    ensure_dependencies,
    load_root_env,
    get_npm_executable,
    check_prerequisites,
    attempt_start_redis,
    Colors
)
from tools.commands.test_logger import TestLogger, LogLevel, LogCategory

# Import test components
from tests.functionality.test_coordinator import TestCoordinator
from tests.functionality.report_generator import ReportGenerator
from tests.functionality.config import config
from tests.functionality.fixtures import cleanup_shared_resources


class OrchestratedTestRunner:
    """Orchestrates system startup and test execution."""
    
    def __init__(self, project_root: Path, logger: TestLogger, 
                 skip_startup: bool = False, test_mode: str = "grouped",
                 timeout: float = 60.0, verbose: bool = False,
                 test_groups: Optional[List[str]] = None, max_workers: int = 4):
        self.project_root = project_root
        self.logger = logger
        self.skip_startup = skip_startup
        self.test_mode = test_mode
        self.timeout = timeout
        self.verbose = verbose
        self.test_groups = test_groups
        self.max_workers = max_workers
        
        self.manager: Optional[ParallelProcessManager] = None
        self.services_status: Dict[str, bool] = {}
        self.shutdown_event = False
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        if not self.shutdown_event:
            self.logger.info(LogCategory.SYSTEM, "Shutdown signal received, cleaning up...")
            self.shutdown_event = True
            self.cleanup()
            sys.exit(0)
    
    async def run(self) -> bool:
        """Run the complete orchestration: startup -> health checks -> tests."""
        try:
            # Step 1: Startup services (if not skipped)
            if not self.skip_startup:
                if not self._startup_services():
                    self.logger.error(LogCategory.STARTUP, "Service startup failed")
                    return False
            else:
                self.logger.info(LogCategory.STARTUP, "Skipping service startup (assume services already running)")
            
            # Step 2: Wait for services to be ready
            if not self.skip_startup:
                self.services_status = self.manager.wait_for_services_ready(
                    timeout=self.timeout,
                    retry_interval=config.health_check_retry_interval
                )
                
                if not all(self.services_status.values()):
                    failed_services = [name for name, ready in self.services_status.items() if not ready]
                    self.logger.error(
                        LogCategory.HEALTH,
                        f"Some services are not ready: {', '.join(failed_services)}",
                        details={"failed_services": failed_services}
                    )
                    # Continue anyway - tests may still be able to run
                else:
                    self.logger.info(LogCategory.HEALTH, "All services are ready")
            else:
                # Assume all services are ready if skipping startup
                self.services_status = {
                    "Backend": True,
                    "Feature Server": True,
                    "Frontend": True,
                    "Database": True,
                    "Redis": True,
                    "WebSocket": True
                }
            
            # Step 3: Run tests
            test_success = await self._run_tests()
            
            return test_success
            
        except KeyboardInterrupt:
            self.logger.warning(LogCategory.SYSTEM, "Test execution interrupted by user")
            return False
        except Exception as e:
            self.logger.error(
                LogCategory.SYSTEM,
                f"Unexpected error during orchestration: {str(e)}",
                error=str(e)
            )
            import traceback
            self.logger.error(
                LogCategory.SYSTEM,
                f"Traceback: {traceback.format_exc()}",
                details={"traceback": traceback.format_exc()}
            )
            return False
        finally:
            self.cleanup()
    
    def _startup_services(self) -> bool:
        """Start all services."""
        self.logger.info(LogCategory.STARTUP, "Starting system services...")
        
        try:
            npm_cmd = get_npm_executable()
        except FileNotFoundError as e:
            self.logger.error(LogCategory.STARTUP, f"npm not found: {e}")
            return False
        
        # Setup services
        self.manager = setup_services(self.project_root, npm_cmd)
        
        # Store paper validator reference if available
        from tools.commands.start_parallel import PaperTradingValidator
        paper_validator = PaperTradingValidator(self.project_root)
        self.manager.paper_validator = paper_validator
        
        # Start all services
        if not self.manager.start_all():
            self.logger.error(LogCategory.STARTUP, "Failed to start all services")
            return False
        
        self.logger.info(LogCategory.STARTUP, "All services started successfully")
        return True
    
    async def _run_tests(self) -> bool:
        """Run functionality tests."""
        self.logger.info(LogCategory.TEST, "Starting test execution...")
        
        # Update config
        config.verbose = self.verbose
        config.max_workers = self.max_workers
        
        # Determine execution mode
        if self.test_mode == "sequential":
            parallel = False
            grouped = False
        elif self.test_mode == "parallel":
            parallel = True
            grouped = False
        else:  # grouped (default)
            parallel = True
            grouped = True
        
        self.logger.info(
            LogCategory.TEST,
            f"Test execution mode: {self.test_mode} (parallel={parallel}, grouped={grouped})"
        )
        
        # Initialize coordinator
        coordinator = TestCoordinator(max_workers=self.max_workers)
        
        try:
            # Run tests
            if self.test_groups:
                self.logger.info(LogCategory.TEST, f"Running specific test groups: {', '.join(self.test_groups)}")
                all_results = await coordinator.run_specific_groups(self.test_groups, parallel=parallel)
            else:
                all_results = await coordinator.run_all_groups(parallel=parallel, grouped=grouped)
            
            # Generate reports
            self.logger.info(LogCategory.TEST, "Generating test reports...")
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
            
            # Print summary
            summary = coordinator.get_summary()
            self.logger.info(LogCategory.TEST, f"Test execution completed: {summary['passed']} passed, {summary['failed']} failed, {summary['warnings']} warnings")
            
            print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
            print(f"{Colors.BOLD}Test Execution Summary{Colors.RESET}")
            print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
            print(f"Total Tests: {summary['total_tests']}")
            print(f"Passed: {Colors.GREEN}{summary['passed']}{Colors.RESET}")
            print(f"Failed: {Colors.ERROR}{summary['failed']}{Colors.RESET}" if summary['failed'] > 0 else f"Failed: {summary['failed']}")
            print(f"Warnings: {Colors.YELLOW}{summary['warnings']}{Colors.RESET}" if summary['warnings'] > 0 else f"Warnings: {summary['warnings']}")
            print(f"Groups Completed: {summary['groups_completed']}/{summary['groups']}")
            
            print(f"\nReports generated:")
            for format_name, path in reports.items():
                print(f"  {format_name.upper()}: {path}")
            print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
            
            # Log errors and warnings
            test_errors = self.logger.get_test_errors()
            test_warnings = self.logger.get_test_warnings()
            
            if test_errors:
                self.logger.error(LogCategory.TEST, f"Test execution completed with {len(test_errors)} errors")
                for entry in test_errors[:5]:  # Log first 5 errors
                    self.logger.error(LogCategory.TEST, entry.message, service=entry.service, error=entry.error)
            
            if test_warnings:
                self.logger.warning(LogCategory.TEST, f"Test execution completed with {len(test_warnings)} warnings")
            
            return summary['failed'] == 0
            
        except Exception as e:
            self.logger.error(
                LogCategory.TEST,
                f"Error during test execution: {str(e)}",
                error=str(e)
            )
            import traceback
            self.logger.error(
                LogCategory.TEST,
                f"Traceback: {traceback.format_exc()}",
                details={"traceback": traceback.format_exc()}
            )
            return False
        finally:
            await cleanup_shared_resources()
    
    def cleanup(self):
        """Cleanup resources."""
        if self.manager and not self.skip_startup:
            self.logger.info(LogCategory.SYSTEM, "Stopping all services...")
            self.manager.stop_all()
        
        # Export logs
        log_file = self.logger.export_json()
        self.logger.info(LogCategory.SYSTEM, f"Logs exported to: {log_file}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Start JackSparrow system and run comprehensive functionality tests"
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
    
    args = parser.parse_args()
    
    # Change to project root
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
    logger.info(LogCategory.STARTUP, "Loading environment configuration...")
    load_root_env(project_root)
    
    # Parse test groups
    test_groups = None
    if args.groups:
        test_groups = [g.strip() for g in args.groups.split(",")]
    
    # Check prerequisites (only if starting services)
    if not args.no_startup:
        # Attempt to start Redis if needed (before prerequisites check)
        logger.info(LogCategory.STARTUP, "Checking Redis availability...")
        attempt_start_redis(project_root)
        
        logger.info(LogCategory.STARTUP, "Checking prerequisites...")
        if not check_prerequisites():
            logger.error(LogCategory.STARTUP, "Prerequisites check failed - some required services are not available")
            logger.info(LogCategory.STARTUP, "You can try running with --no-startup if services are already running")
            sys.exit(1)
        
        # Ensure dependencies
        logger.info(LogCategory.STARTUP, "Ensuring dependencies are installed...")
        try:
            npm_cmd = get_npm_executable()
            ensure_dependencies(project_root, npm_cmd)
        except FileNotFoundError as e:
            logger.error(LogCategory.STARTUP, f"Dependency check failed: {e}")
            sys.exit(1)
    
    # Create and run orchestrator
    orchestrator = OrchestratedTestRunner(
        project_root=project_root,
        logger=logger,
        skip_startup=args.no_startup,
        test_mode=args.test_mode,
        timeout=args.timeout,
        verbose=args.verbose,
        test_groups=test_groups,
        max_workers=args.max_workers
    )
    
    success = await orchestrator.run()
    
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
    
    # Export logs
    log_file = logger.export_json()
    print(f"Detailed logs exported to: {log_file}\n")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

