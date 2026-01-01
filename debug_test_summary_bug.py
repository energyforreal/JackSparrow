#!/usr/bin/env python3
"""
Integrated debugging script for test summary bug.

This script demonstrates the systematic debugging process used to identify
and fix the test summary bug in start_and_test.py.

The bug was that TestCoordinator summaries showed 0 tests because a fresh
coordinator was created instead of using the one that actually ran the tests.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from tests.functionality.test_coordinator import TestCoordinator


class TestSummaryBugDebugger:
    """Debug the test summary bug systematically."""

    def __init__(self):
        self.coordinator = None
        self.results = None

    async def step_1_verify_imports(self):
        """Step 1: Verify TestCoordinator can be imported and initialized."""
        print("=== Step 1: Verify TestCoordinator Import ===")

        try:
            tc = TestCoordinator()
            print('✓ TestCoordinator imported successfully')
            print(f'✓ Found {len(tc.test_groups)} test groups')
            for group_name, group in tc.test_groups.items():
                print(f'  - {group_name}: {len(group.test_modules)} modules')
            return True
        except Exception as e:
            print(f'✗ Import error: {e}')
            return False

    async def step_2_test_individual_module(self):
        """Step 2: Test loading and running an individual test module."""
        print("\n=== Step 2: Test Individual Module Execution ===")

        try:
            tc = TestCoordinator()
            module_name = "test_database_operations"
            print(f"Loading test module: {module_name}")

            # Load and run the test
            suite = await tc.load_test_module(module_name)
            if suite:
                print(f"✓ Successfully loaded suite: {suite.test_name}")

                # Run the test
                await suite.setup()
                await suite.run_all_tests()
                await suite.teardown()

                # Check results
                results = suite.results
                print(f"✓ Test completed with {len(results)} individual test results")
                for result in results:
                    status_icon = "✓" if result.status.name == "PASS" else "⚠" if result.status.name == "WARNING" else "✗"
                    print(f"  {status_icon} {result.name}: {result.status.name}")

                return True
            else:
                print("✗ Failed to load test suite")
                return False

        except Exception as e:
            print(f"✗ Error in individual module test: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def step_3_reproduce_bug(self):
        """Step 3: Reproduce the bug - fresh coordinator shows 0 tests."""
        print("\n=== Step 3: Reproduce the Bug ===")

        try:
            # Create coordinator and run tests
            print("Running tests with first coordinator...")
            tc1 = TestCoordinator()
            results = await tc1.run_test_group("infrastructure", parallel=True)
            print(f"✓ Ran {len(results)} test suites")

            # Get summary from the same coordinator
            print("Getting summary from same coordinator...")
            summary1 = tc1.get_summary()
            print(f"✓ Summary from tc1: {summary1}")

            # Create a new coordinator and check its summary (should be empty)
            print("Creating fresh coordinator...")
            tc2 = TestCoordinator()
            summary2 = tc2.get_summary()
            print(f"✓ Summary from tc2 (fresh): {summary2}")

            # Check if bug is reproduced
            if summary1['total_tests'] > 0 and summary2['total_tests'] == 0:
                print("✓ BUG CONFIRMED: Fresh coordinator shows 0 tests")
                print("  This explains why start_and_test.py showed 'Passed: 0, Failed: 0, Warnings: 0'")
                self.coordinator = tc1
                return True
            else:
                print("✗ Bug not reproduced")
                return False

        except Exception as e:
            print(f"✗ Error reproducing bug: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def step_4_verify_fix(self):
        """Step 4: Verify the fix works (simulate the corrected behavior)."""
        print("\n=== Step 4: Verify Fix Works ===")

        if not self.coordinator:
            print("✗ No coordinator from previous step")
            return False

        try:
            # Simulate what the fixed run_tests method should return
            print("Simulating fixed behavior...")
            tc = TestCoordinator()

            # Run tests and get summary from SAME coordinator
            results = await tc.run_specific_groups(["infrastructure"], parallel=True)
            summary = tc.get_summary()

            print(f"✓ Summary from fixed approach: {summary}")

            if summary['total_tests'] > 0:
                print("✓ Fix working: Tests are being counted correctly")
                print(f"  - Total tests: {summary['total_tests']}")
                print(f"  - Passed: {summary['passed']}")
                print(f"  - Failed: {summary['failed']}")
                print(f"  - Warnings: {summary['warnings']}")
                return True
            else:
                print("✗ Fix not working: Still showing 0 tests")
                return False

        except Exception as e:
            print(f"✗ Error verifying fix: {e}")
            return False

    async def run_all_steps(self):
        """Run all debugging steps in sequence."""
        print("🔍 Starting systematic debugging of test summary bug")
        print("=" * 60)

        steps = [
            self.step_1_verify_imports,
            self.step_2_test_individual_module,
            self.step_3_reproduce_bug,
            self.step_4_verify_fix
        ]

        results = []
        for step in steps:
            result = await step()
            results.append(result)
            if not result:
                print(f"\n❌ Step failed. Stopping debugging process.")
                break

        print("\n" + "=" * 60)
        successful_steps = sum(results)
        print(f"✅ Completed {successful_steps}/{len(steps)} debugging steps")

        if successful_steps == len(steps):
            print("🎉 Bug successfully identified and fix verified!")
            print("\nThe issue was that start_and_test.py created a fresh TestCoordinator")
            print("for summaries instead of using the one that actually ran the tests.")
        else:
            print("❌ Debugging incomplete - some steps failed")


async def main():
    """Main entry point."""
    debugger = TestSummaryBugDebugger()
    await debugger.run_all_steps()


if __name__ == "__main__":
    asyncio.run(main())
