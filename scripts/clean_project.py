#!/usr/bin/env python3
"""
Project cleanup script.

Removes redundant and old files, keeping only those used for current functionality.
Run with --dry-run (default) to preview changes, --execute to apply them.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


# Files/dirs to DELETE (relative to project root)
TO_DELETE = [
    # Root ad-hoc tests
    "test_decision.py",
    "test_agent_config.py",
    "test_market_data.py",
    "test_reasoning.py",
    "test_agent_status.py",
    "test_agent_websocket.py",
    "test_agent_market_data.py",
    "test_delta_api.py",
    "test_event_handlers.py",
    "test_market_data_service.py",
    "test_confidence_fix.py",
    "test_fluctuation.py",
    "test_paper_trade_flow.py",
    "test_paper_trade_logging.py",
    "test_startup.py",
    "test_model_discovery.py",
    # Root debug/verify scripts
    "debug_agent_service_response.py",
    "debug_test_summary_bug.py",
    "verify_confidence_fix.py",
    "verify_model_integration.py",
    # Root output files
    "direct_output.txt",
    "error_logging_report.json",
    "log_analysis_report.json",
    # Root utility scripts (move candidates - delete if not moved)
    "check_trades.py",
    "run_project_test.py",
    # Duplicate/improved scripts
    "tools/commands/start_parallel_improved.py",
    "tools/commands/start_and_test_improved.py",
]

# Coverage artifacts (glob patterns)
COVERAGE_PATTERNS = [".coverage", ".coverage.*", "htmlcov"]

# Move: (src, dst) relative to project root
TO_MOVE = [
    ("AUDIT_FINAL_REPORT_20260118.md", "docs/archive/audit-final-report-20260118.md"),
    ("SYSTEM_MONITORING_REPORT.md", "docs/archive/system-monitoring-report.md"),
]

# Old test reports: keep latest N, delete rest
TEST_REPORTS_DIR = "tests/functionality/reports"
TEST_REPORTS_KEEP = 2
TEST_REPORTS_GLOB = "comprehensive_test_report_*.json"


def collect_coverage_files(root: Path) -> list[Path]:
    """Collect coverage artifact paths."""
    found = []
    for p in COVERAGE_PATTERNS:
        if "*" in p:
            for f in root.glob(p):
                if f.is_file() or f.is_dir():
                    found.append(f)
        else:
            f = root / p
            if f.exists():
                found.append(f)
    return found


def collect_old_test_reports(root: Path) -> list[Path]:
    """Collect old test reports, keeping latest N by mtime."""
    reports_dir = root / TEST_REPORTS_DIR
    if not reports_dir.exists():
        return []
    files = sorted(
        reports_dir.glob(TEST_REPORTS_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return list(files[TEST_REPORTS_KEEP:])


def collect_model_backups(root: Path) -> list[Path]:
    """Collect model backup files."""
    storage = root / "agent" / "model_storage"
    if not storage.exists():
        return []
    return list(storage.rglob("*.backup"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean redundant/old project files"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform deletions and moves (default: dry-run)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when --execute is set",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    root = PROJECT_ROOT

    # Collect all targets
    to_delete_paths: list[Path] = []
    for rel in TO_DELETE:
        p = root / rel
        if p.exists():
            to_delete_paths.append(p)

    to_move: list[tuple[Path, Path]] = []
    for src_rel, dst_rel in TO_MOVE:
        src = root / src_rel
        dst = root / dst_rel
        if src.exists():
            to_move.append((src, dst))

    coverage_files = collect_coverage_files(root)
    old_reports = collect_old_test_reports(root)
    model_backups = collect_model_backups(root)

    all_to_delete = to_delete_paths + coverage_files + old_reports + model_backups

    # Log file
    log_dir = root / "logs" / "cleanup"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"clean_project_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    log_lines: list[str] = []

    def log(msg: str) -> None:
        log_lines.append(msg)
        print(msg)

    log(f"Clean project {'(DRY-RUN)' if dry_run else '(EXECUTE)'} - {datetime.now(timezone.utc).isoformat()}")
    log("")

    if not all_to_delete and not to_move:
        log("No files to clean.")
        log_file.write_text("\n".join(log_lines), encoding="utf-8")
        return 0

    # Report
    if to_delete_paths:
        log("Files to DELETE:")
        for p in sorted(to_delete_paths):
            log(f"  - {p.relative_to(root)}")
        log("")

    if coverage_files:
        log("Coverage artifacts to DELETE:")
        for p in sorted(coverage_files):
            log(f"  - {p.relative_to(root)}")
        log("")

    if old_reports:
        log(f"Old test reports to DELETE (keeping latest {TEST_REPORTS_KEEP}):")
        for p in sorted(old_reports):
            log(f"  - {p.relative_to(root)}")
        log("")

    if model_backups:
        log("Model backups to DELETE:")
        for p in sorted(model_backups):
            log(f"  - {p.relative_to(root)}")
        log("")

    if to_move:
        log("Files to MOVE:")
        for src, dst in to_move:
            log(f"  - {src.relative_to(root)} -> {dst.relative_to(root)}")
        log("")

    if dry_run:
        log("Run with --execute to apply changes. Use --yes to skip confirmation.")
        log_file.write_text("\n".join(log_lines), encoding="utf-8")
        return 0

    # Execute
    if not args.yes:
        try:
            resp = input("Proceed with cleanup? [y/N]: ").strip().lower()
        except EOFError:
            resp = "n"
        if resp not in ("y", "yes"):
            log("Aborted.")
            log_file.write_text("\n".join(log_lines), encoding="utf-8")
            return 1

    errors = []

    # Create archive dir for moves
    (root / "docs" / "archive").mkdir(parents=True, exist_ok=True)

    for p in all_to_delete:
        try:
            if p.is_dir():
                import shutil
                shutil.rmtree(p)
                log(f"Deleted dir: {p.relative_to(root)}")
            else:
                p.unlink()
                log(f"Deleted: {p.relative_to(root)}")
        except OSError as e:
            err = f"Failed to delete {p}: {e}"
            log(err)
            errors.append(err)

    for src, dst in to_move:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            log(f"Moved: {src.relative_to(root)} -> {dst.relative_to(root)}")
        except OSError as e:
            err = f"Failed to move {src} -> {dst}: {e}"
            log(err)
            errors.append(err)

    log("")
    log(f"Log written to {log_file}")
    if errors:
        log(f"Completed with {len(errors)} error(s).")
        log_file.write_text("\n".join(log_lines), encoding="utf-8")
        return 1

    log("Cleanup completed successfully.")
    log_file.write_text("\n".join(log_lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
