"""Test coordinator for parallel execution and dependency management."""

import asyncio
import importlib
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from tests.functionality.config import config
from tests.functionality.utils import TestSuiteBase, TestStatus, TestSuiteResult


@dataclass
class TestGroup:
    """Test group configuration."""
    name: str
    test_modules: List[str]
    dependencies: List[str]
    status: TestStatus = TestStatus.PASS
    results: List[TestSuiteResult] = field(default_factory=list)


class TestCoordinator:
    """Coordinates parallel test execution with dependency management."""
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or config.max_workers
        self.test_groups: Dict[str, TestGroup] = {}
        self.execution_order: List[str] = []
        self._setup_groups()
    
    def _setup_groups(self):
        """Setup test groups from configuration."""
        for group_name, test_modules in config.test_groups.items():
            dependencies = config.group_dependencies.get(group_name, [])
            self.test_groups[group_name] = TestGroup(
                name=group_name,
                test_modules=test_modules,
                dependencies=dependencies
            )
    
    def _resolve_execution_order(self) -> List[str]:
        """Resolve execution order based on dependencies."""
        # Topological sort
        visited: Set[str] = set()
        temp_visited: Set[str] = set()
        order: List[str] = []
        
        def visit(group_name: str):
            if group_name in temp_visited:
                raise ValueError(f"Circular dependency detected involving {group_name}")
            if group_name in visited:
                return
            
            temp_visited.add(group_name)
            
            # Visit dependencies first
            if group_name in self.test_groups:
                for dep in self.test_groups[group_name].dependencies:
                    if dep in self.test_groups:
                        visit(dep)
            
            temp_visited.remove(group_name)
            visited.add(group_name)
            order.append(group_name)
        
        for group_name in self.test_groups:
            if group_name not in visited:
                visit(group_name)
        
        return order
    
    async def load_test_module(self, module_name: str) -> Optional[TestSuiteBase]:
        """Load a test module and return the test suite instance."""
        try:
            # Import the module
            module = importlib.import_module(f"tests.functionality.{module_name}")
            
            # Find the test suite class (should be named *TestSuite)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, TestSuiteBase) and 
                    attr != TestSuiteBase):
                    # Instantiate the test suite
                    test_name = module_name.replace("test_", "").replace("_", " ")
                    return attr(test_name)
            
            return None
        except Exception as e:
            print(f"Failed to load test module {module_name}: {e}")
            return None
    
    async def run_test_suite(self, test_suite: TestSuiteBase) -> TestSuiteResult:
        """Run a single test suite."""
        test_suite.start_time = datetime.utcnow()
        
        try:
            await test_suite.setup()
            await test_suite.run_all_tests()
            await test_suite.teardown()
        except Exception as e:
            # Add error result
            from tests.functionality.utils import TestResult
            error_result = TestResult(
                name="setup_error",
                status=TestStatus.FAIL,
                duration_ms=0.0,
                error=str(e)
            )
            test_suite.add_result(error_result)
        finally:
            test_suite.end_time = datetime.utcnow()
        
        # Generate result
        status = test_suite.get_status()
        return TestSuiteResult(
            suite_name=test_suite.test_name,
            status=status,
            start_time=test_suite.start_time,
            end_time=test_suite.end_time,
            duration_ms=test_suite.get_duration(),
            results=test_suite.results,
            issues=test_suite.get_issues(),
            solutions=test_suite.get_solutions()
        )
    
    async def run_test_group(self, group_name: str, parallel: bool = True) -> List[TestSuiteResult]:
        """Run all tests in a group."""
        if group_name not in self.test_groups:
            return []
        
        group = self.test_groups[group_name]
        results: List[TestSuiteResult] = []
        
        # Load all test suites
        test_suites: List[TestSuiteBase] = []
        for module_name in group.test_modules:
            suite = await self.load_test_module(module_name)
            if suite:
                test_suites.append(suite)
        
        if not test_suites:
            return results
        
        # Run tests
        if parallel and len(test_suites) > 1:
            # Run in parallel
            tasks = [self.run_test_suite(suite) for suite in test_suites]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions
            results = [r for r in results if isinstance(r, TestSuiteResult)]
        else:
            # Run sequentially
            for suite in test_suites:
                result = await self.run_test_suite(suite)
                results.append(result)
        
        group.results = results
        group.status = TestStatus.PASS if all(r.status == TestStatus.PASS for r in results) else TestStatus.FAIL
        
        return results
    
    async def run_all_groups(self, parallel: bool = True, grouped: bool = True) -> Dict[str, List[TestSuiteResult]]:
        """Run all test groups."""
        execution_order = self._resolve_execution_order()
        all_results: Dict[str, List[TestSuiteResult]] = {}
        
        if grouped:
            # Run groups sequentially, tests within groups in parallel
            for group_name in execution_order:
                print(f"Running test group: {group_name}")
                results = await self.run_test_group(group_name, parallel=parallel)
                all_results[group_name] = results
        else:
            # Run all groups in parallel (only independent groups)
            independent_groups = [g for g in execution_order if not self.test_groups[g].dependencies]
            dependent_groups = [g for g in execution_order if g not in independent_groups]
            
            # Run independent groups in parallel
            if independent_groups:
                tasks = [self.run_test_group(g, parallel=parallel) for g in independent_groups]
                independent_results = await asyncio.gather(*tasks)
                for group_name, results in zip(independent_groups, independent_results):
                    all_results[group_name] = results
            
            # Run dependent groups sequentially
            for group_name in dependent_groups:
                results = await self.run_test_group(group_name, parallel=parallel)
                all_results[group_name] = results
        
        return all_results
    
    async def run_specific_groups(self, group_names: List[str], parallel: bool = True) -> Dict[str, List[TestSuiteResult]]:
        """Run specific test groups."""
        all_results: Dict[str, List[TestSuiteResult]] = {}
        
        for group_name in group_names:
            if group_name in self.test_groups:
                results = await self.run_test_group(group_name, parallel=parallel)
                all_results[group_name] = results
        
        return all_results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get execution summary."""
        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_warnings = 0
        total_degraded = 0
        
        for group in self.test_groups.values():
            for result in group.results:
                total_tests += len(result.results)
                for test_result in result.results:
                    if test_result.status == TestStatus.PASS:
                        total_passed += 1
                    elif test_result.status == TestStatus.FAIL:
                        total_failed += 1
                    elif test_result.status == TestStatus.WARNING:
                        total_warnings += 1
                    elif test_result.status == TestStatus.DEGRADED:
                        total_degraded += 1
        
        return {
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "warnings": total_warnings,
            "degraded": total_degraded,
            "groups": len(self.test_groups),
            "groups_completed": sum(1 for g in self.test_groups.values() if g.results)
        }

