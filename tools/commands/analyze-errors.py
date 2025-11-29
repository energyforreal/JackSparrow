#!/usr/bin/env python3
"""Analyze error and warning logs to generate comprehensive error reports.

Parses error/warning log files and generates summary reports with:
- Error counts by type
- Error counts by component
- Most frequent errors
- Error trends over time
- Recent critical errors
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from collections import Counter, defaultdict

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

try:
    from agent.core.error_metrics import get_error_summary
    from agent.core.logging_utils import get_session_id
except ImportError:
    get_error_summary = None
    get_session_id = None


def parse_json_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a JSON log line.
    
    Args:
        line: JSON log line
        
    Returns:
        Parsed log entry or None if invalid
    """
    line = line.strip()
    if not line:
        return None
    
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def analyze_log_file(log_file: Path, min_level: str = "ERROR") -> Dict[str, Any]:
    """Analyze a log file for errors/warnings.
    
    Args:
        log_file: Path to log file
        min_level: Minimum log level to analyze (ERROR, WARNING, etc.)
        
    Returns:
        Dictionary with analysis results
    """
    if not log_file.exists():
        return {
            "file": str(log_file),
            "exists": False,
            "entries": [],
            "error_count": 0,
            "warning_count": 0,
        }
    
    level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level_num = level_order.get(min_level.upper(), 2)
    
    entries = []
    error_count = 0
    warning_count = 0
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                log_entry = parse_json_log_line(line)
                if not log_entry:
                    continue
                
                level = log_entry.get("level", "").upper()
                level_num = level_order.get(level, 0)
                
                if level_num >= min_level_num:
                    entries.append({
                        **log_entry,
                        "_line_number": line_num,
                    })
                    
                    if level in ("ERROR", "CRITICAL"):
                        error_count += 1
                    elif level == "WARNING":
                        warning_count += 1
    except Exception as e:
        return {
            "file": str(log_file),
            "exists": True,
            "error": str(e),
            "entries": [],
            "error_count": 0,
            "warning_count": 0,
        }
    
    return {
        "file": str(log_file),
        "exists": True,
        "entries": entries,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def generate_error_report(log_files: List[Path], output_file: Optional[Path] = None) -> Dict[str, Any]:
    """Generate comprehensive error report.
    
    Args:
        log_files: List of log file paths to analyze
        output_file: Optional path to save JSON report
        
    Returns:
        Dictionary with error report
    """
    project_root = Path(__file__).resolve().parents[2]
    logs_dir = project_root / "logs" / "agent"
    
    # Default log files if none specified
    if not log_files:
        log_files = [
            logs_dir / "errors.log",
            logs_dir / "warnings.log",
            logs_dir / "agent.log",
        ]
    
    all_entries = []
    errors_by_type = Counter()
    errors_by_component = Counter()
    warnings_by_key = Counter()
    
    # Analyze each log file
    file_results = []
    for log_file in log_files:
        result = analyze_log_file(log_file)
        file_results.append(result)
        
        if result.get("exists") and result.get("entries"):
            all_entries.extend(result["entries"])
    
    # Analyze entries
    for entry in all_entries:
        level = entry.get("level", "").upper()
        
        if level in ("ERROR", "CRITICAL"):
            error_type = entry.get("error_type") or entry.get("error", {}).get("type") or "UnknownError"
            component = entry.get("component") or entry.get("service") or "unknown"
            
            errors_by_type[error_type] += 1
            errors_by_component[component] += 1
        elif level == "WARNING":
            warning_key = entry.get("message") or "unknown_warning"
            warnings_by_key[warning_key] += 1
    
    # Get most frequent errors (top 10)
    most_frequent_errors = [
        {"error_type": error_type, "count": count}
        for error_type, count in errors_by_type.most_common(10)
    ]
    
    # Get errors by component (top 10)
    top_error_components = [
        {"component": component, "count": count}
        for component, count in errors_by_component.most_common(10)
    ]
    
    # Get most frequent warnings (top 10)
    most_frequent_warnings = [
        {"warning": warning, "count": count}
        for warning, count in warnings_by_key.most_common(10)
    ]
    
    # Get recent critical errors (last 20)
    recent_errors = sorted(
        [e for e in all_entries if e.get("level", "").upper() in ("ERROR", "CRITICAL")],
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )[:20]
    
    # Try to get runtime error metrics if available
    runtime_metrics = None
    if get_error_summary:
        try:
            runtime_metrics = get_error_summary()
        except Exception:
            pass
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": get_session_id() if get_session_id else None,
        "summary": {
            "total_errors": sum(r["error_count"] for r in file_results),
            "total_warnings": sum(r["warning_count"] for r in file_results),
            "total_log_entries_analyzed": len(all_entries),
        },
        "file_results": [
            {
                "file": r["file"],
                "exists": r["exists"],
                "error_count": r.get("error_count", 0),
                "warning_count": r.get("warning_count", 0),
            }
            for r in file_results
        ],
        "errors_by_type": dict(errors_by_type.most_common(20)),
        "errors_by_component": dict(errors_by_component.most_common(20)),
        "warnings_by_key": dict(warnings_by_key.most_common(20)),
        "most_frequent_errors": most_frequent_errors,
        "top_error_components": top_error_components,
        "most_frequent_warnings": most_frequent_warnings,
        "recent_critical_errors": recent_errors[:20],
        "runtime_metrics": runtime_metrics,
    }
    
    # Save to file if requested
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    
    return report


def print_report(report: Dict[str, Any]) -> None:
    """Print error report to console.
    
    Args:
        report: Error report dictionary
    """
    print("=" * 70)
    print("ERROR ANALYSIS REPORT")
    print("=" * 70)
    print(f"Generated: {report['generated_at']}")
    if report.get("session_id"):
        print(f"Session ID: {report['session_id']}")
    print()
    
    # Summary
    summary = report["summary"]
    print(f"SUMMARY:")
    print(f"  Total Errors: {summary['total_errors']}")
    print(f"  Total Warnings: {summary['total_warnings']}")
    print(f"  Log Entries Analyzed: {summary['total_log_entries_analyzed']}")
    print()
    
    # Most frequent errors
    if report.get("most_frequent_errors"):
        print("MOST FREQUENT ERRORS:")
        for i, error in enumerate(report["most_frequent_errors"][:10], 1):
            print(f"  {i}. {error['error_type']}: {error['count']} occurrences")
        print()
    
    # Top error components
    if report.get("top_error_components"):
        print("ERRORS BY COMPONENT:")
        for i, component in enumerate(report["top_error_components"][:10], 1):
            print(f"  {i}. {component['component']}: {component['count']} errors")
        print()
    
    # Most frequent warnings
    if report.get("most_frequent_warnings"):
        print("MOST FREQUENT WARNINGS:")
        for i, warning in enumerate(report["most_frequent_warnings"][:10], 1):
            warning_text = warning["warning"][:60] + "..." if len(warning["warning"]) > 60 else warning["warning"]
            print(f"  {i}. {warning_text}: {warning['count']} occurrences")
        print()
    
    # Runtime metrics if available
    if report.get("runtime_metrics"):
        runtime = report["runtime_metrics"]
        print("RUNTIME METRICS:")
        print(f"  Total Errors: {runtime.get('total_errors', 0)}")
        print(f"  Total Warnings: {runtime.get('total_warnings', 0)}")
        if runtime.get("error_rate_per_minute"):
            print(f"  Error Rate: {runtime['error_rate_per_minute']:.2f} errors/minute")
        print()
    
    # Recent critical errors
    if report.get("recent_critical_errors"):
        print("RECENT CRITICAL ERRORS (last 5):")
        for i, error in enumerate(report["recent_critical_errors"][:5], 1):
            timestamp = error.get("timestamp", "unknown")
            error_type = error.get("error_type") or error.get("error", {}).get("type") or "Unknown"
            component = error.get("component") or error.get("service") or "unknown"
            message = error.get("message", "")[:50]
            print(f"  {i}. [{timestamp}] {component}: {error_type}")
            if message:
                print(f"     {message}")
        print()
    
    print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze error and warning logs",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--log-file",
        type=str,
        action="append",
        help="Path to log file to analyze (can be specified multiple times)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to save JSON report (default: logs/error/analysis-{timestamp}.json)"
    )
    parser.add_argument(
        "--min-level",
        type=str,
        default="ERROR",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Minimum log level to analyze (default: ERROR)"
    )
    
    args = parser.parse_args()
    
    # Build log file list
    log_files = []
    if args.log_file:
        log_files = [Path(f) for f in args.log_file]
    
    # Generate report
    output_file = None
    if args.output:
        output_file = Path(args.output)
    else:
        # Default output location
        project_root = Path(__file__).resolve().parents[2]
        logs_dir = project_root / "logs" / "error"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = logs_dir / f"analysis-{timestamp}.json"
    
    try:
        report = generate_error_report(log_files, output_file)
        print_report(report)
        print(f"\nReport saved to: {output_file}")
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

