"""
Git Repository Audit Checks

This module contains Git repository audit checks for the JackSparrow project.
"""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_repository_status() -> AuditResult:
    """Check Git repository status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=10
        )

        if result.returncode != 0:
            return AuditResult(
                check_name="repository_status",
                category="git_repository",
                severity="low",
                status="error",
                message="Git repository status check failed",
                details="Could not run git status"
            )

        uncommitted_changes = result.stdout.strip()
        if uncommitted_changes:
            lines = uncommitted_changes.split('\n')
            return AuditResult(
                check_name="repository_status",
                category="git_repository",
                severity="low",
                status="warning",
                message=f"Found {len(lines)} uncommitted changes",
                details="Uncommitted files:\n" + uncommitted_changes[:500]
            )

        return AuditResult(
            check_name="repository_status",
            category="git_repository",
            severity="low",
            status="pass",
            message="Repository is clean"
        )

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return AuditResult(
            check_name="repository_status",
            category="git_repository",
            severity="low",
            status="warning",
            message="Git not available",
            recommendations=["Ensure Git is installed"]
        )


def check_gitignore_completeness() -> AuditResult:
    """Check .gitignore completeness."""
    gitignore = project_root / ".gitignore"
    if not gitignore.exists():
        return AuditResult(
            check_name="gitignore_completeness",
            category="git_repository",
            severity="low",
            status="fail",
            message=".gitignore file not found",
            recommendations=["Create .gitignore file"]
        )

    try:
        with open(gitignore, 'r', encoding='utf-8') as f:
            content = f.read()

        essential_patterns = ['.env', '__pycache__/', 'node_modules/', '*.log']
        missing_patterns = []

        for pattern in essential_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)

        if missing_patterns:
            return AuditResult(
                check_name="gitignore_completeness",
                category="git_repository",
                severity="low",
                status="fail",
                message=f"Missing essential .gitignore patterns: {', '.join(missing_patterns)}",
                recommendations=["Add missing patterns to .gitignore"]
            )

        return AuditResult(
            check_name="gitignore_completeness",
            category="git_repository",
            severity="low",
            status="pass",
            message=".gitignore is properly configured"
        )

    except (UnicodeDecodeError, OSError):
        return AuditResult(
            check_name="gitignore_completeness",
            category="git_repository",
            severity="low",
            status="error",
            message="Could not read .gitignore file"
        )