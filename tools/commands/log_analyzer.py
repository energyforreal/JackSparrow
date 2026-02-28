#!/usr/bin/env python3
"""
Enhanced Log Analyzer for JackSparrow Trading Agent

Parses structured JSON logs, extracts errors and warnings, identifies patterns,
and generates comprehensive error reports.
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, Counter
from dataclasses import dataclass, field

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# ANSI color codes
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: datetime
    level: str
    service: str
    component: Optional[str]
    message: str
    event: Optional[str]
    correlation_id: Optional[str]
    request_id: Optional[str]
    error_type: Optional[str]
    error_message: Optional[str]
    stack_trace: Optional[str]
    raw_entry: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorPattern:
    """Error pattern analysis."""
    pattern: str
    count: int
    first_seen: datetime
    last_seen: datetime
    services: List[str]
    components: List[str]
    sample_messages: List[str]


@dataclass
class LogAnalysisReport:
    """Comprehensive log analysis report."""
    total_entries: int
    time_range: Tuple[datetime, datetime]
    error_count: int
    warning_count: int
    critical_count: int
    errors_by_service: Dict[str, int]
    errors_by_component: Dict[str, int]
    error_patterns: List[ErrorPattern]
    recent_errors: List[LogEntry]
    recent_warnings: List[LogEntry]
    unhandled_exceptions: List[LogEntry]
    missing_error_logging: List[Dict[str, Any]]
    performance_issues: List[LogEntry]


class EnhancedLogAnalyzer:
    """Enhanced log analyzer for structured logging."""

    def __init__(self, logs_root: Optional[Path] = None):
        """Initialize log analyzer.

        Args:
            logs_root: Root directory containing log files. Defaults to project logs/.
        """
        if logs_root is None:
            logs_root = project_root / "logs"

        self.logs_root = logs_root
        self.entries: List[LogEntry] = []
        self.error_patterns: Dict[str, ErrorPattern] = {}

    def analyze_all_logs(self, max_age_hours: int = 24) -> LogAnalysisReport:
        """Analyze all log files and generate comprehensive report.

        Args:
            max_age_hours: Only analyze logs from the last N hours

        Returns:
            Comprehensive analysis report
        """
        print(f"{Colors.BLUE}[INFO] Analyzing log files...{Colors.RESET}")

        # Load all log entries
        self._load_log_entries(max_age_hours)

        # Analyze entries
        report = self._generate_report()

        return report

    def _load_log_entries(self, max_age_hours: int):
        """Load and parse log entries from all log files."""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        log_files = self._find_log_files()

        for log_file in log_files:
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue

                        entry = self._parse_log_line(line, log_file, line_num)
                        if entry:
                            # Handle timezone-aware vs naive datetime comparison
                            try:
                                if entry.timestamp >= cutoff_time:
                                    self.entries.append(entry)
                            except TypeError:
                                # Handle timezone mismatch by converting to naive
                                if entry.timestamp.tzinfo is not None and cutoff_time.tzinfo is None:
                                    entry_naive = entry.timestamp.replace(tzinfo=None)
                                    if entry_naive >= cutoff_time:
                                        self.entries.append(entry)
                                elif entry.timestamp.tzinfo is None and cutoff_time.tzinfo is not None:
                                    cutoff_naive = cutoff_time.replace(tzinfo=None)
                                    if entry.timestamp >= cutoff_naive:
                                        self.entries.append(entry)
                                else:
                                    # Both have timezone info or both naive, should work
                                    if entry.timestamp >= cutoff_time:
                                        self.entries.append(entry)

            except Exception as e:
                print(f"{Colors.YELLOW}[WARN] Failed to read {log_file}: {e}{Colors.RESET}", file=sys.stderr)

        print(f"{Colors.GREEN}[OK] Loaded {len(self.entries)} log entries{Colors.RESET}")

    def _find_log_files(self) -> List[Path]:
        """Find all log files to analyze."""
        log_files = []

        if not self.logs_root.exists():
            return log_files

        # Standard log directories
        log_dirs = [
            self.logs_root / "backend",
            self.logs_root / "agent",
            self.logs_root / "frontend"
        ]

        for log_dir in log_dirs:
            if log_dir.exists():
                log_files.extend(log_dir.glob("*.log"))

        # Also check root logs directory
        if self.logs_root.exists():
            log_files.extend(self.logs_root.glob("*.log"))

        return log_files

    def _parse_log_line(self, line: str, log_file: Path, line_num: int) -> Optional[LogEntry]:
        """Parse a single log line into structured entry."""
        try:
            # Try JSON parsing first (structured logs)
            data = json.loads(line)

            # Extract timestamp
            timestamp_str = data.get("timestamp") or data.get("time") or data.get("@timestamp")
            if timestamp_str:
                # Handle different timestamp formats
                if "T" in timestamp_str:
                    # ISO format
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                else:
                    # Try parsing as unix timestamp or other formats
                    try:
                        timestamp = datetime.fromtimestamp(float(timestamp_str))
                    except (ValueError, TypeError):
                        timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            return LogEntry(
                timestamp=timestamp,
                level=data.get("level", "INFO").upper(),
                service=data.get("service", log_file.stem),
                component=data.get("component") or data.get("logger"),
                message=data.get("message") or data.get("msg") or data.get("event", ""),
                event=data.get("event"),
                correlation_id=data.get("correlation_id") or data.get("request_id"),
                request_id=data.get("request_id"),
                error_type=data.get("error", {}).get("type") if isinstance(data.get("error"), dict) else data.get("error_type"),
                error_message=data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else data.get("error_message"),
                stack_trace=data.get("error", {}).get("stack") if isinstance(data.get("error"), dict) else data.get("exc_info"),
                raw_entry=data
            )

        except json.JSONDecodeError:
            # Not JSON, try to parse as plain text log
            return self._parse_plain_text_log(line, log_file)

        except Exception as e:
            # Failed to parse, create minimal entry
            return LogEntry(
                timestamp=datetime.now(),
                level="UNKNOWN",
                service=log_file.stem,
                component=None,
                message=f"Failed to parse log line: {e}",
                event=None,
                correlation_id=None,
                request_id=None,
                error_type=None,
                error_message=None,
                stack_trace=None,
                raw_entry={"raw_line": line}
            )

    def _parse_plain_text_log(self, line: str, log_file: Path) -> Optional[LogEntry]:
        """Parse plain text log line."""
        # Simple pattern matching for common log formats
        patterns = [
            # [2023-12-28 10:30:02] ERROR: message
            r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(\w+):\s+(.+)',
            # 2023-12-28 10:30:02 ERROR message
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+(.+)',
            # ERROR: message
            r'(\w+):\s+(.+)'
        ]

        for pattern in patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 3:
                    # Has timestamp
                    timestamp_str = groups[0]
                    level = groups[1].upper()
                    message = groups[2]
                elif len(groups) == 2:
                    # No timestamp
                    level = groups[0].upper()
                    message = groups[1]
                    timestamp_str = None
                else:
                    continue

                try:
                    if timestamp_str:
                        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    else:
                        timestamp = datetime.now()
                except ValueError:
                    timestamp = datetime.now()

                return LogEntry(
                    timestamp=timestamp,
                    level=level,
                    service=log_file.stem,
                    component=None,
                    message=message,
                    event=None,
                    correlation_id=None,
                    request_id=None,
                    error_type=None,
                    error_message=None,
                    stack_trace=None,
                    raw_entry={"raw_line": line}
                )

        # If no pattern matches, skip this line
        return None

    def _generate_report(self) -> LogAnalysisReport:
        """Generate comprehensive analysis report."""
        if not self.entries:
            return LogAnalysisReport(
                total_entries=0,
                time_range=(datetime.now(), datetime.now()),
                error_count=0,
                warning_count=0,
                critical_count=0,
                errors_by_service={},
                errors_by_component={},
                error_patterns=[],
                recent_errors=[],
                recent_warnings=[],
                unhandled_exceptions=[],
                missing_error_logging=[],
                performance_issues=[]
            )

        # Sort entries by timestamp
        self.entries.sort(key=lambda x: x.timestamp)

        # Calculate time range
        time_range = (self.entries[0].timestamp, self.entries[-1].timestamp)

        # Categorize entries
        errors = [e for e in self.entries if e.level in ("ERROR", "CRITICAL", "FATAL")]
        warnings = [e for e in self.entries if e.level == "WARNING"]
        critical_errors = [e for e in errors if e.level in ("CRITICAL", "FATAL")]

        # Count by service and component
        errors_by_service = Counter(e.service for e in errors)
        errors_by_component = Counter(e.component for e in errors if e.component)

        # Find error patterns
        error_patterns = self._identify_error_patterns(errors)

        # Find recent errors (last 50)
        recent_errors = sorted(errors, key=lambda x: x.timestamp, reverse=True)[:50]

        # Find recent warnings (last 20)
        recent_warnings = sorted(warnings, key=lambda x: x.timestamp, reverse=True)[:20]

        # Find unhandled exceptions
        unhandled_exceptions = [
            e for e in errors
            if "exception" in e.message.lower() or "traceback" in e.message.lower() or e.stack_trace
        ]

        # Identify missing error logging (this is a heuristic)
        missing_error_logging = self._identify_missing_error_logging()

        # Find performance issues
        performance_issues = [
            e for e in self.entries
            if any(keyword in e.message.lower() for keyword in ["timeout", "slow", "latency", "performance"])
        ]

        return LogAnalysisReport(
            total_entries=len(self.entries),
            time_range=time_range,
            error_count=len(errors),
            warning_count=len(warnings),
            critical_count=len(critical_errors),
            errors_by_service=dict(errors_by_service),
            errors_by_component=dict(errors_by_component),
            error_patterns=list(error_patterns.values()),
            recent_errors=recent_errors,
            recent_warnings=recent_warnings,
            unhandled_exceptions=unhandled_exceptions,
            missing_error_logging=missing_error_logging,
            performance_issues=performance_issues
        )

    def _identify_error_patterns(self, errors: List[LogEntry]) -> Dict[str, ErrorPattern]:
        """Identify recurring error patterns."""
        patterns = {}

        for error in errors:
            # Create pattern key from error message (simplified)
            message = error.message.lower()
            # Remove timestamps, IDs, and variable parts
            pattern = re.sub(r'\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}', '', message)
            pattern = re.sub(r'\b[a-f0-9]{8,}\b', '', pattern)  # Remove UUIDs
            pattern = re.sub(r'\d+', '', pattern)  # Remove numbers
            pattern = re.sub(r'\s+', ' ', pattern).strip()  # Normalize whitespace

            if len(pattern) < 10:  # Skip very short patterns
                continue

            if pattern not in patterns:
                patterns[pattern] = ErrorPattern(
                    pattern=pattern,
                    count=0,
                    first_seen=error.timestamp,
                    last_seen=error.timestamp,
                    services=[],
                    components=[],
                    sample_messages=[]
                )

            p = patterns[pattern]
            p.count += 1
            p.last_seen = max(p.last_seen, error.timestamp)
            p.first_seen = min(p.first_seen, error.timestamp)

            if error.service not in p.services:
                p.services.append(error.service)
            if error.component and error.component not in p.components:
                p.components.append(error.component)
            if len(p.sample_messages) < 3 and error.message not in p.sample_messages:
                p.sample_messages.append(error.message)

        # Only keep patterns that appear more than once
        return {k: v for k, v in patterns.items() if v.count > 1}

    def _identify_missing_error_logging(self) -> List[Dict[str, Any]]:
        """Identify potential missing error logging (heuristic analysis)."""
        missing = []

        # Look for exceptions that might not be logged
        for entry in self.entries:
            if "exception" in entry.message.lower() and not entry.error_type:
                missing.append({
                    "type": "untyped_exception",
                    "service": entry.service,
                    "component": entry.component,
                    "message": entry.message[:100],
                    "timestamp": entry.timestamp
                })

        return missing

    def print_report(self, report: LogAnalysisReport):
        """Print comprehensive analysis report."""
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}[LOG ANALYSIS REPORT]{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")

        print(f"\n{Colors.BOLD}[SUMMARY] Summary:{Colors.RESET}")
        print(f"  Total Log Entries: {Colors.BLUE}{report.total_entries:,}{Colors.RESET}")
        print(f"  Time Range: {report.time_range[0].strftime('%Y-%m-%d %H:%M:%S')} to {report.time_range[1].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Errors: {Colors.RED}{report.error_count:,}{Colors.RESET}")
        print(f"  Warnings: {Colors.YELLOW}{report.warning_count:,}{Colors.RESET}")
        print(f"  Critical Errors: {Colors.RED}{report.critical_count:,}{Colors.RESET}")

        if report.errors_by_service:
            print(f"\n{Colors.BOLD}[ERRORS BY SERVICE] Errors by Service:{Colors.RESET}")
            for service, count in sorted(report.errors_by_service.items(), key=lambda x: x[1], reverse=True):
                print(f"  {service}: {Colors.RED}{count}{Colors.RESET}")

        if report.errors_by_component:
            print(f"\n{Colors.BOLD}[ERRORS BY COMPONENT] Errors by Component:{Colors.RESET}")
            for component, count in sorted(report.errors_by_component.items(), key=lambda x: x[1], reverse=True)[:10]:  # Top 10
                print(f"  {component}: {Colors.RED}{count}{Colors.RESET}")

        if report.error_patterns:
            print(f"\n{Colors.BOLD}[RECURRING PATTERNS] Recurring Error Patterns:{Colors.RESET}")
            for i, pattern in enumerate(sorted(report.error_patterns, key=lambda x: x.count, reverse=True)[:5], 1):  # Top 5
                print(f"  {i}. {Colors.YELLOW}'{pattern.pattern[:60]}...'{Colors.RESET}")
                print(f"     Count: {Colors.RED}{pattern.count}{Colors.RESET} | Services: {', '.join(pattern.services)}")
                print(f"     First: {pattern.first_seen.strftime('%m-%d %H:%M')} | Last: {pattern.last_seen.strftime('%m-%d %H:%M')}")

        if report.unhandled_exceptions:
            print(f"\n{Colors.BOLD}[CRITICAL] Unhandled Exceptions ({len(report.unhandled_exceptions)}):{Colors.RESET}")
            for exc in report.unhandled_exceptions[:5]:  # Show first 5
                print(f"  {Colors.RED}{exc.timestamp.strftime('%H:%M:%S')}{Colors.RESET} {exc.service}")
                print(f"    {exc.message[:80]}{'...' if len(exc.message) > 80 else ''}")

        if report.performance_issues:
            print(f"\n{Colors.BOLD}[PERF] Performance Issues ({len(report.performance_issues)}):{Colors.RESET}")
            for issue in report.performance_issues[:3]:  # Show first 3
                print(f"  {Colors.YELLOW}{issue.timestamp.strftime('%H:%M:%S')}{Colors.RESET} {issue.service}: {issue.message[:60]}")

        if report.recent_errors:
            print(f"\n{Colors.BOLD}[ERRORS] Recent Errors (last {min(10, len(report.recent_errors))}):{Colors.RESET}")
            for error in report.recent_errors[:10]:
                component = f"[{error.component}]" if error.component else ""
                print(f"  {Colors.RED}{error.timestamp.strftime('%H:%M:%S')}{Colors.RESET} {error.service}{component}: {error.message[:60]}")

        if report.recent_warnings:
            print(f"\n{Colors.BOLD}[WARNINGS] Recent Warnings (last {min(5, len(report.recent_warnings))}):{Colors.RESET}")
            for warning in report.recent_warnings[:5]:
                component = f"[{warning.component}]" if warning.component else ""
                print(f"  {Colors.YELLOW}{warning.timestamp.strftime('%H:%M:%S')}{Colors.RESET} {warning.service}{component}: {warning.message[:50]}")

        if report.missing_error_logging:
            print(f"\n{Colors.BOLD}[MISSING LOGGING] Potential Missing Error Logging:{Colors.RESET}")
            for missing in report.missing_error_logging[:3]:  # Show first 3
                print(f"  {Colors.BLUE}{missing['service']}{Colors.RESET}: {missing['message'][:60]}")

        # Overall assessment
        health_score = self._calculate_log_health_score(report)
        if health_score >= 0.8:
            health_color = Colors.GREEN
            assessment = "EXCELLENT"
        elif health_score >= 0.6:
            health_color = Colors.YELLOW
            assessment = "GOOD"
        else:
            health_color = Colors.RED
            assessment = "NEEDS ATTENTION"

        print(f"\n{Colors.BOLD}[HEALTH] Log Health Score: {health_color}{health_score:.1%} ({assessment}){Colors.RESET}")

        if report.error_count == 0 and report.warning_count == 0:
            print(f"\n{Colors.GREEN}[OK] No errors or warnings found in logs!{Colors.RESET}")
        elif report.error_count == 0:
            print(f"\n{Colors.GREEN}[OK] No errors found, but {report.warning_count} warnings detected.{Colors.RESET}")
        else:
            print(f"\n{Colors.YELLOW}[WARN] {report.error_count} errors and {report.warning_count} warnings found.{Colors.RESET}")

    def _calculate_log_health_score(self, report: LogAnalysisReport) -> float:
        """Calculate log health score based on error patterns."""
        if report.total_entries == 0:
            return 1.0

        # Base score starts at 1.0
        score = 1.0

        # Deduct for errors (more severe deduction)
        error_rate = report.error_count / report.total_entries
        score -= min(0.5, error_rate * 2)  # Max 50% deduction for errors

        # Deduct for warnings (less severe)
        warning_rate = report.warning_count / report.total_entries
        score -= min(0.2, warning_rate * 0.5)  # Max 20% deduction for warnings

        # Deduct for critical errors
        if report.critical_count > 0:
            score -= min(0.3, report.critical_count * 0.1)  # Additional deduction for critical errors

        # Deduct for unhandled exceptions
        if report.unhandled_exceptions:
            score -= min(0.2, len(report.unhandled_exceptions) * 0.05)

        return max(0.0, score)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced log analyzer for JackSparrow")
    parser.add_argument("--logs-root", type=Path, help="Root directory containing log files")
    parser.add_argument("--max-age-hours", type=int, default=24, help="Only analyze logs from last N hours")
    parser.add_argument("--output-json", type=Path, help="Save report as JSON to file")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")

    args = parser.parse_args()

    analyzer = EnhancedLogAnalyzer(args.logs_root)

    try:
        report = analyzer.analyze_all_logs(args.max_age_hours)

        if not args.quiet:
            analyzer.print_report(report)

        if args.output_json:
            # Convert report to JSON-serializable format
            json_report = {
                "total_entries": report.total_entries,
                "time_range": [
                    report.time_range[0].isoformat(),
                    report.time_range[1].isoformat()
                ],
                "error_count": report.error_count,
                "warning_count": report.warning_count,
                "critical_count": report.critical_count,
                "errors_by_service": report.errors_by_service,
                "errors_by_component": report.errors_by_component,
                "error_patterns": [
                    {
                        "pattern": p.pattern,
                        "count": p.count,
                        "first_seen": p.first_seen.isoformat(),
                        "last_seen": p.last_seen.isoformat(),
                        "services": p.services,
                        "components": p.components,
                        "sample_messages": p.sample_messages
                    }
                    for p in report.error_patterns
                ],
                "recent_errors": [
                    {
                        "timestamp": e.timestamp.isoformat(),
                        "level": e.level,
                        "service": e.service,
                        "component": e.component,
                        "message": e.message,
                        "event": e.event,
                        "correlation_id": e.correlation_id,
                        "error_type": e.error_type,
                        "error_message": e.error_message
                    }
                    for e in report.recent_errors
                ],
                "recent_warnings": [
                    {
                        "timestamp": w.timestamp.isoformat(),
                        "level": w.level,
                        "service": w.service,
                        "component": w.component,
                        "message": w.message
                    }
                    for w in report.recent_warnings
                ],
                "unhandled_exceptions": [
                    {
                        "timestamp": e.timestamp.isoformat(),
                        "service": e.service,
                        "component": e.component,
                        "message": e.message,
                        "stack_trace": e.stack_trace
                    }
                    for e in report.unhandled_exceptions
                ],
                "missing_error_logging": report.missing_error_logging,
                "performance_issues": [
                    {
                        "timestamp": p.timestamp.isoformat(),
                        "service": p.service,
                        "component": p.component,
                        "message": p.message
                    }
                    for p in report.performance_issues
                ]
            }

            with open(args.output_json, 'w', encoding='utf-8') as f:
                json.dump(json_report, f, indent=2, ensure_ascii=False)

            print(f"\n{Colors.GREEN}[OK] Report saved to {args.output_json}{Colors.RESET}")

    except Exception as e:
        print(f"{Colors.RED}[ERROR] Log analysis failed: {e}{Colors.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()