"""
Service Health Audit Checks

This module contains service health audit checks for the JackSparrow project.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_service_health() -> AuditResult:
    """Check service health endpoints."""
    # This would normally check actual service endpoints
    # For now, just check if health check scripts exist
    health_scripts = [
        "tools/commands/health_check.py",
        "scripts/check_backend_health.py"
    ]

    found_scripts = 0
    for script in health_scripts:
        if (project_root / script).exists():
            found_scripts += 1

    if found_scripts == 0:
        return AuditResult(
            check_name="service_health",
            category="service_health",
            severity="critical",
            status="fail",
            message="No health check scripts found",
            recommendations=["Create health check scripts"]
        )

    return AuditResult(
        check_name="service_health",
        category="service_health",
        severity="critical",
        status="pass",
        message=f"Found {found_scripts} health check scripts"
    )


def check_log_analysis() -> AuditResult:
    """Analyze log files for issues."""
    logs_dir = project_root / "logs"
    if not logs_dir.exists():
        return AuditResult(
            check_name="log_analysis",
            category="service_health",
            severity="medium",
            status="warning",
            message="Logs directory not found",
            recommendations=["Ensure logging is configured"]
        )

    log_files = list(logs_dir.glob("*.log"))
    if not log_files:
        return AuditResult(
            check_name="log_analysis",
            category="service_health",
            severity="medium",
            status="warning",
            message="No log files found",
            recommendations=["Run services to generate logs"]
        )

    return AuditResult(
        check_name="log_analysis",
        category="service_health",
        severity="medium",
        status="pass",
        message=f"Found {len(log_files)} log files"
    )