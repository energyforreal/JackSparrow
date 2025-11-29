#!/usr/bin/env python3
"""View and filter error and warning logs.

Provides an interactive way to view recent errors and warnings with filtering options.
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


# ANSI color codes for terminal output
class Colors:
    """ANSI color codes."""
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


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


def read_log_file(log_file: Path, max_lines: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read and parse log file.
    
    Args:
        log_file: Path to log file
        max_lines: Maximum number of lines to read (for tail)
        
    Returns:
        List of parsed log entries
    """
    if not log_file.exists():
        return []
    
    entries = []
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if max_lines:
                lines = lines[-max_lines:]
            
            for line in lines:
                entry = parse_json_log_line(line)
                if entry:
                    entries.append(entry)
    except Exception as e:
        print(f"Error reading log file {log_file}: {e}", file=sys.stderr)
        return []
    
    return entries


def filter_entries(
    entries: List[Dict[str, Any]],
    component: Optional[str] = None,
    error_type: Optional[str] = None,
    level: Optional[str] = None,
    min_time: Optional[datetime] = None,
    max_time: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Filter log entries based on criteria.
    
    Args:
        entries: List of log entries
        component: Filter by component name
        error_type: Filter by error type
        level: Filter by log level (ERROR, WARNING, etc.)
        min_time: Filter entries after this time
        max_time: Filter entries before this time
        
    Returns:
        Filtered list of log entries
    """
    filtered = []
    
    for entry in entries:
        # Filter by level
        if level:
            entry_level = entry.get("level", "").upper()
            if entry_level != level.upper():
                continue
        
        # Filter by component
        if component:
            entry_component = entry.get("component") or entry.get("service") or ""
            if component.lower() not in entry_component.lower():
                continue
        
        # Filter by error type
        if error_type:
            entry_error_type = entry.get("error_type") or entry.get("error", {}).get("type") or ""
            if error_type.lower() not in entry_error_type.lower():
                continue
        
        # Filter by time
        if min_time or max_time:
            entry_time_str = entry.get("timestamp", "")
            if entry_time_str:
                try:
                    entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                    if min_time and entry_time < min_time:
                        continue
                    if max_time and entry_time > max_time:
                        continue
                except Exception:
                    pass
        
        filtered.append(entry)
    
    return filtered


def format_entry(entry: Dict[str, Any], show_full: bool = False) -> str:
    """Format a log entry for display.
    
    Args:
        entry: Log entry dictionary
        show_full: Whether to show full details
        
    Returns:
        Formatted string
    """
    level = entry.get("level", "").upper()
    timestamp = entry.get("timestamp", "unknown")
    component = entry.get("component") or entry.get("service") or "unknown"
    message = entry.get("message", "")
    
    # Color based on level
    color = Colors.RESET
    if level in ("ERROR", "CRITICAL"):
        color = Colors.RED
    elif level == "WARNING":
        color = Colors.YELLOW
    elif level == "INFO":
        color = Colors.GREEN
    
    # Format timestamp
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        time_str = timestamp
    
    lines = [
        f"{color}{Colors.BOLD}[{level}]{Colors.RESET} {Colors.CYAN}{time_str}{Colors.RESET} | {Colors.BLUE}{component}{Colors.RESET}"
    ]
    
    if message:
        lines.append(f"  {Colors.BOLD}Message:{Colors.RESET} {message}")
    
    # Show error details if present
    if level in ("ERROR", "CRITICAL"):
        error_type = entry.get("error_type") or entry.get("error", {}).get("type")
        error_message = entry.get("error_message") or entry.get("error", {}).get("message")
        
        if error_type:
            lines.append(f"  {Colors.BOLD}Error Type:{Colors.RESET} {error_type}")
        if error_message:
            lines.append(f"  {Colors.BOLD}Error:{Colors.RESET} {error_message}")
    
    # Show correlation ID if present
    correlation_id = entry.get("correlation_id")
    if correlation_id:
        lines.append(f"  {Colors.BOLD}Correlation ID:{Colors.RESET} {correlation_id}")
    
    # Show full details if requested
    if show_full:
        lines.append(f"  {Colors.BOLD}Full Entry:{Colors.RESET}")
        lines.append(json.dumps(entry, indent=4, default=str))
    
    return "\n".join(lines)


def view_errors(
    log_files: List[Path],
    component: Optional[str] = None,
    error_type: Optional[str] = None,
    level: Optional[str] = None,
    tail: Optional[int] = None,
    follow: bool = False,
    show_full: bool = False
) -> None:
    """View and display errors.
    
    Args:
        log_files: List of log file paths
        component: Filter by component
        error_type: Filter by error type
        level: Filter by log level
        tail: Show only last N entries
        follow: Follow log file (not implemented)
        show_full: Show full entry details
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
    
    # Collect all entries
    all_entries = []
    for log_file in log_files:
        entries = read_log_file(log_file, max_lines=tail * 100 if tail else None)
        all_entries.extend(entries)
    
    # Filter entries
    filtered_entries = filter_entries(
        all_entries,
        component=component,
        error_type=error_type,
        level=level
    )
    
    # Sort by timestamp (most recent first)
    filtered_entries.sort(
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )
    
    # Apply tail limit
    if tail:
        filtered_entries = filtered_entries[:tail]
    
    # Display entries
    print(f"{Colors.BOLD}Found {len(filtered_entries)} entries{Colors.RESET}\n")
    
    for i, entry in enumerate(filtered_entries, 1):
        print(f"{Colors.MAGENTA}--- Entry {i}/{len(filtered_entries)} ---{Colors.RESET}")
        print(format_entry(entry, show_full=show_full))
        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="View and filter error/warning logs",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--log-file",
        type=str,
        action="append",
        help="Path to log file (can be specified multiple times)"
    )
    parser.add_argument(
        "--component",
        type=str,
        help="Filter by component name"
    )
    parser.add_argument(
        "--error-type",
        type=str,
        help="Filter by error type"
    )
    parser.add_argument(
        "--level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Filter by log level"
    )
    parser.add_argument(
        "--tail",
        type=int,
        help="Show only last N entries"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Show full entry details"
    )
    
    args = parser.parse_args()
    
    # Build log file list
    log_files = []
    if args.log_file:
        log_files = [Path(f) for f in args.log_file]
    
    try:
        view_errors(
            log_files=log_files,
            component=args.component,
            error_type=args.error_type,
            level=args.level,
            tail=args.tail,
            show_full=args.full
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error viewing logs: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

