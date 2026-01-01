"""Main entry point for running all functionality tests."""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from tests.functionality.test_coordinator import TestCoordinator
from tests.functionality.report_generator import ReportGenerator
from tests.functionality.config import config
from tests.functionality.fixtures import cleanup_shared_resources


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run comprehensive functionality tests")
    parser.add_argument("--parallel", action="store_true", help="Run tests in parallel")
    parser.add_argument("--grouped", action="store_true", help="Run groups sequentially, tests within groups in parallel")
    parser.add_argument("--sequential", action="store_true", help="Run all tests sequentially")
    parser.add_argument("--max-workers", type=int, default=4, help="Maximum parallel workers")
    parser.add_argument("--groups", type=str, help="Comma-separated list of groups to run")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--generate-only", action="store_true", help="Generate report from previous run only")
    
    args = parser.parse_args()
    
    config.verbose = args.verbose
    config.max_workers = args.max_workers
    
    print("=" * 80)
    print("JackSparrow Trading Agent - Comprehensive Functionality Test Suite")
    print("=" * 80)
    print(f"Started at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    
    if args.generate_only:
        print("Generating report from previous run...")
        generator = ReportGenerator()
        reports = generator.generate_all_reports()
        print(f"\nReports generated:")
        for format_name, path in reports.items():
            print(f"  {format_name.upper()}: {path}")
        return
    
    # Determine execution mode
    if args.sequential:
        parallel = False
        grouped = False
        mode = "Sequential"
    elif args.grouped or (args.parallel and not args.groups):
        parallel = True
        grouped = True
        mode = "Grouped Parallel"
    elif args.parallel:
        parallel = True
        grouped = False
        mode = "Fully Parallel"
    else:
        # Default: grouped parallel
        parallel = True
        grouped = True
        mode = "Grouped Parallel (default)"
    
    print(f"Execution Mode: {mode}")
    if parallel:
        print(f"Max Workers: {config.max_workers}")
    print()
    
    # Initialize coordinator
    coordinator = TestCoordinator(max_workers=config.max_workers)
    
    try:
        # Run tests
        if args.groups:
            group_list = [g.strip() for g in args.groups.split(",")]
            print(f"Running specific groups: {', '.join(group_list)}")
            all_results = await coordinator.run_specific_groups(group_list, parallel=parallel)
        else:
            all_results = await coordinator.run_all_groups(parallel=parallel, grouped=grouped)
        
        # Generate reports
        print("\n" + "=" * 80)
        print("Generating Reports...")
        print("=" * 80)
        
        generator = ReportGenerator()
        for group_name, results in all_results.items():
            generator.add_results(group_name, results)
        
        reports = generator.generate_all_reports()
        
        # Print summary
        summary = coordinator.get_summary()
        print("\n" + "=" * 80)
        print("Test Execution Summary")
        print("=" * 80)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Warnings: {summary['warnings']}")
        print(f"Degraded: {summary['degraded']}")
        print(f"Groups Completed: {summary['groups_completed']}/{summary['groups']}")
        
        print(f"\nReports generated:")
        for format_name, path in reports.items():
            print(f"  {format_name.upper()}: {path}")
        
        print(f"\nCompleted at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 80)
        
        # Exit with appropriate code
        if summary['failed'] > 0:
            sys.exit(1)
        elif summary['warnings'] > 0:
            sys.exit(0)  # Warnings don't fail the test run
        else:
            sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\nTest execution interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nFatal error during test execution: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Cleanup
        await cleanup_shared_resources()


if __name__ == "__main__":
    asyncio.run(main())

