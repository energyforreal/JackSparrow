"""
Performance Audit Checks

This module contains performance audit checks for the JackSparrow project.
"""

from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_performance_baselines() -> AuditResult:
    """Check performance baselines."""
    # Basic check for performance-related scripts
    perf_scripts = [
        "scripts/benchmark_prediction_pipeline.py",
        "scripts/quick_performance_test.py"
    ]

    found_scripts = 0
    for script in perf_scripts:
        if (project_root / script).exists():
            found_scripts += 1

    if found_scripts == 0:
        return AuditResult(
            check_name="performance_baselines",
            category="performance",
            severity="medium",
            status="warning",
            message="No performance testing scripts found",
            recommendations=["Create performance benchmark scripts"]
        )

    return AuditResult(
        check_name="performance_baselines",
        category="performance",
        severity="medium",
        status="pass",
        message=f"Found {found_scripts} performance testing scripts"
    )