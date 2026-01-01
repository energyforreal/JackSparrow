"""Shared utilities for functionality tests."""

import asyncio
import functools
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
import threading
from dataclasses import dataclass, field


class TestStatus(Enum):
    """Test execution status."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    SKIPPED = "SKIPPED"


@dataclass
class TestResult:
    """Individual test result."""
    name: str
    status: TestStatus
    duration_ms: float
    details: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    solutions: List[str] = field(default_factory=list)
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TestSuiteResult:
    """Test suite result container."""
    suite_name: str
    status: TestStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: float = 0.0
    results: List[TestResult] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    solutions: List[str] = field(default_factory=list)
    
    def get_duration(self) -> float:
        """Calculate duration if end_time is set."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return (datetime.utcnow() - self.start_time).total_seconds() * 1000
    
    def get_status(self) -> TestStatus:
        """Determine overall status from results."""
        if not self.results:
            return TestStatus.SKIPPED
        
        has_fail = any(r.status == TestStatus.FAIL for r in self.results)
        has_warning = any(r.status == TestStatus.WARNING for r in self.results)
        has_degraded = any(r.status == TestStatus.DEGRADED for r in self.results)
        
        if has_fail:
            return TestStatus.FAIL
        if has_warning:
            return TestStatus.WARNING
        if has_degraded:
            return TestStatus.DEGRADED
        return TestStatus.PASS


class TestSuiteBase:
    """Base class for functionality test suites."""
    
    def __init__(self, test_name: str):
        self.test_name = test_name
        self.results: List[TestResult] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self._lock = threading.Lock()
    
    async def setup(self):
        """Setup shared resources (called once per test group)."""
        pass
    
    async def run_all_tests(self):
        """Run all tests in this suite. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement run_all_tests")
    
    async def teardown(self):
        """Cleanup (called after all tests complete)."""
        pass
    
    def add_result(self, result: TestResult):
        """Add a test result (thread-safe)."""
        with self._lock:
            self.results.append(result)
    
    def get_status(self) -> TestStatus:
        """Get overall test suite status."""
        if not self.results:
            return TestStatus.SKIPPED
        
        suite_result = TestSuiteResult(
            suite_name=self.test_name,
            status=TestStatus.PASS,
            start_time=self.start_time or datetime.utcnow(),
            results=self.results
        )
        return suite_result.get_status()
    
    def get_duration(self) -> float:
        """Get test suite duration in milliseconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        if self.start_time:
            return (datetime.utcnow() - self.start_time).total_seconds() * 1000
        return 0.0
    
    def get_issues(self) -> List[str]:
        """Get all issues from test results."""
        issues = []
        for result in self.results:
            issues.extend(result.issues)
        return issues
    
    def get_solutions(self) -> List[str]:
        """Get all solutions from test results."""
        solutions = []
        for result in self.results:
            solutions.extend(result.solutions)
        return solutions
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate test report."""
        return {
            "test_name": self.test_name,
            "status": self.get_status().value,
            "results": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "duration_ms": r.duration_ms,
                    "details": r.details,
                    "issues": r.issues,
                    "solutions": r.solutions,
                    "error": r.error
                }
                for r in self.results
            ],
            "duration_ms": self.get_duration(),
            "issues": self.get_issues(),
            "solutions": self.get_solutions(),
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.status == TestStatus.PASS),
            "failed": sum(1 for r in self.results if r.status == TestStatus.FAIL),
            "warnings": sum(1 for r in self.results if r.status == TestStatus.WARNING),
            "degraded": sum(1 for r in self.results if r.status == TestStatus.DEGRADED)
        }


def parallel_safe(func: Callable) -> Callable:
    """Decorator to ensure thread-safe execution of test methods."""
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if hasattr(self, '_lock'):
            with self._lock:
                return await func(self, *args, **kwargs)
        return await func(self, *args, **kwargs)
    return wrapper


def measure_time(func: Callable) -> Callable:
    """Decorator to measure execution time."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            return result, duration
        except Exception as e:
            duration = (time.time() - start) * 1000
            raise e
    return wrapper


class ServiceHealthChecker:
    """Check health of external services."""
    
    @staticmethod
    async def check_backend(url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Check backend health."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}/api/v1/health", timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "status": "up",
                            "health_score": data.get("health_score", 0.0),
                            "latency_ms": 0.0  # Could measure actual latency
                        }
                    return {"status": "down", "error": f"HTTP {resp.status}"}
        except asyncio.TimeoutError:
            return {"status": "down", "error": "Timeout"}
        except Exception as e:
            return {"status": "down", "error": str(e)}
    
    @staticmethod
    async def check_redis(url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Check Redis connectivity.
        
        Args:
            url: Redis connection URL
            timeout: Connection timeout in seconds (default: 5.0)
            
        Returns:
            Dictionary with status and optional error message
        """
        try:
            import redis.asyncio as redis
            # Use asyncio timeout wrapper for better control
            client = redis.from_url(url, socket_connect_timeout=timeout)
            await asyncio.wait_for(client.ping(), timeout=timeout)
            await client.aclose()
            return {"status": "up"}
        except asyncio.TimeoutError:
            return {"status": "down", "error": f"Timeout connecting to server (>{timeout}s)"}
        except Exception as e:
            return {"status": "down", "error": str(e)}
    
    @staticmethod
    async def check_database(url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Check database connectivity."""
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": timeout})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "up"}
        except Exception as e:
            return {"status": "down", "error": str(e)}


def generate_solution(issue: str, context: Dict[str, Any] = None) -> str:
    """Generate a solution for a given issue."""
    context = context or {}
    
    # Common solutions based on issue patterns
    solutions_map = {
        "connection": "Check service is running and URL is correct",
        "timeout": "Increase timeout or check network connectivity",
        "authentication": "Verify API keys and credentials are correct",
        "model": "Check model files exist and are valid",
        "database": "Verify database is running and connection string is correct",
        "redis": "Check Redis is running and accessible",
        "websocket": "Verify WebSocket server is running and port is correct"
    }
    
    issue_lower = issue.lower()
    for key, solution in solutions_map.items():
        if key in issue_lower:
            return solution
    
    return "Review logs and documentation for troubleshooting steps"

