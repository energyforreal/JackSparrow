#!/usr/bin/env python3
"""Quick script to run agent functionality tests."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from tests.functionality.test_coordinator import TestCoordinator
from tests.functionality.report_generator import ReportGenerator
from tests.functionality.config import config
from tests.functionality.fixtures import cleanup_shared_resources


async def main():
    """Run agent functionality tests."""
    print("=" * 80)
    print("JackSparrow Trading Agent - Agent Functionality Test Suite")
    print("=" * 80)
    print()
    
    # Initialize coordinator
    coordinator = TestCoordinator(max_workers=config.max_workers)
    
    try:
        # Run agent functionality test group
        print("Running agent functionality tests...")
        print()
        
        results = await coordinator.run_test_group("agent-logic", parallel=False)
        
        # Generate reports
        print("\n" + "=" * 80)
        print("Generating Reports...")
        print("=" * 80)
        
        generator = ReportGenerator()
        generator.add_results("agent-logic", results)
        
        reports = generator.generate_all_reports()
        
        # Print summary
        print("\n" + "=" * 80)
        print("Test Execution Summary")
        print("=" * 80)
        
        total_tests = 0
        passed = 0
        failed = 0
        warnings = 0
        
        for result in results:
            total_tests += len(result.results)
            for test_result in result.results:
                if test_result.status.value == "PASS":
                    passed += 1
                elif test_result.status.value == "FAIL":
                    failed += 1
                elif test_result.status.value == "WARNING":
                    warnings += 1
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Warnings: {warnings}")
        
        print(f"\nReports generated:")
        for format_name, path in reports.items():
            print(f"  {format_name.upper()}: {path}")
        
        print("=" * 80)
        
        # Exit with appropriate code
        if failed > 0:
            sys.exit(1)
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

