"""
Database and Model Audit Checks

This module contains database and ML model audit checks for the JackSparrow project.
"""

from pathlib import Path
from typing import Dict, List, Optional

project_root = Path(__file__).parent.parent.parent

from scripts.comprehensive_audit import AuditResult


def check_database_schema() -> AuditResult:
    """Check database schema integrity."""
    # Basic check for database-related files
    schema_files = list(project_root.glob("**/schema.py"))
    migration_files = list(project_root.glob("**/migrations/**"))

    if not schema_files and not migration_files:
        return AuditResult(
            check_name="database_schema",
            category="database_models",
            severity="high",
            status="warning",
            message="No database schema files found",
            recommendations=["Ensure database schema is properly defined"]
        )

    return AuditResult(
        check_name="database_schema",
        category="database_models",
        severity="high",
        status="pass",
        message="Database schema files are present"
    )


def check_model_files() -> AuditResult:
    """Check ML model files."""
    model_dir = project_root / "agent" / "model_storage"
    if not model_dir.exists():
        return AuditResult(
            check_name="model_files",
            category="database_models",
            severity="high",
            status="fail",
            message="Model storage directory not found",
            recommendations=["Create agent/model_storage/ directory"]
        )

    model_files = list(model_dir.glob("**/*"))
    if not model_files:
        return AuditResult(
            check_name="model_files",
            category="database_models",
            severity="high",
            status="warning",
            message="No model files found",
            recommendations=["Train and save ML models"]
        )

    return AuditResult(
        check_name="model_files",
        category="database_models",
        severity="high",
        status="pass",
        message=f"Found {len(model_files)} model-related files"
    )