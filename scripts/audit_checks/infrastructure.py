"""
Infrastructure Audit Checks

This module contains infrastructure audit checks for the JackSparrow project.
"""

from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_docker_configuration() -> AuditResult:
    """Check Docker configuration."""
    issues = []

    docker_compose = project_root / "docker-compose.yml"
    if not docker_compose.exists():
        issues.append("docker-compose.yml not found")

    dockerfiles = list(project_root.glob("**/Dockerfile*"))
    if not dockerfiles:
        issues.append("No Dockerfile found in project")

    if issues:
        return AuditResult(
            check_name="docker_configuration",
            category="infrastructure",
            severity="high",
            status="fail",
            message="Docker configuration issues found",
            details="Issues:\n" + '\n'.join(f"- {issue}" for issue in issues),
            recommendations=["Create docker-compose.yml", "Add Dockerfile for each service"]
        )

    return AuditResult(
        check_name="docker_configuration",
        category="infrastructure",
        severity="high",
        status="pass",
        message="Docker configuration is present"
    )


def check_cicd_pipeline() -> AuditResult:
    """Check CI/CD pipeline configuration."""
    cicd_file = project_root / ".github" / "workflows" / "cicd.yml"
    if not cicd_file.exists():
        return AuditResult(
            check_name="cicd_pipeline",
            category="infrastructure",
            severity="medium",
            status="warning",
            message="CI/CD pipeline not found",
            recommendations=["Create .github/workflows/cicd.yml"]
        )

    return AuditResult(
        check_name="cicd_pipeline",
        category="infrastructure",
        severity="medium",
        status="pass",
        message="CI/CD pipeline is configured"
    )