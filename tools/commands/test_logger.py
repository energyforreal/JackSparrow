"""Enhanced logging system for orchestrated startup and test execution."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


class LogLevel(Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogCategory(Enum):
    """Log categories for organization."""
    STARTUP = "startup"
    HEALTH = "health"
    TEST = "test"
    SYSTEM = "system"


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: datetime
    level: LogLevel
    category: LogCategory
    message: str
    service: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert log entry to dictionary."""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        result["level"] = self.level.value
        result["category"] = self.category.value
        return result


class TestLogger:
    """Enhanced logger for capturing errors, warnings, and issues."""
    
    def __init__(self, log_dir: Path, verbose: bool = False):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.entries: List[LogEntry] = []
        self._startup_errors: List[LogEntry] = []
        self._startup_warnings: List[LogEntry] = []
        self._test_errors: List[LogEntry] = []
        self._test_warnings: List[LogEntry] = []
        self._health_issues: List[LogEntry] = []
        
        # ANSI color codes
        self.colors = {
            "DEBUG": "\033[36m",      # Cyan
            "INFO": "\033[32m",       # Green
            "WARNING": "\033[33m",    # Yellow
            "ERROR": "\033[91m",      # Red
            "CRITICAL": "\033[95m",   # Magenta
            "RESET": "\033[0m",
            "BOLD": "\033[1m"
        }
    
    def log(self, level: LogLevel, category: LogCategory, message: str, 
            service: Optional[str] = None, error: Optional[str] = None,
            details: Optional[Dict[str, Any]] = None) -> LogEntry:
        """Log a message with structured information."""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            level=level,
            category=category,
            message=message,
            service=service,
            error=error,
            details=details or {}
        )
        
        self.entries.append(entry)
        
        # Categorize for quick access
        if level in (LogLevel.ERROR, LogLevel.CRITICAL):
            if category == LogCategory.STARTUP:
                self._startup_errors.append(entry)
            elif category == LogCategory.TEST:
                self._test_errors.append(entry)
            elif category == LogCategory.HEALTH:
                self._health_issues.append(entry)
        
        if level == LogLevel.WARNING:
            if category == LogCategory.STARTUP:
                self._startup_warnings.append(entry)
            elif category == LogCategory.TEST:
                self._test_warnings.append(entry)
        
        # Print to console
        self._print_entry(entry)
        
        return entry
    
    def _print_entry(self, entry: LogEntry):
        """Print log entry to console with color coding."""
        color = self.colors.get(entry.level.value, "")
        reset = self.colors["RESET"]
        
        # Format: [TIMESTAMP] [LEVEL] [CATEGORY] [SERVICE] Message
        service_str = f"[{entry.service}] " if entry.service else ""
        category_str = f"[{entry.category.value.upper()}] " if entry.category else ""
        
        prefix = f"{color}[{entry.level.value}]{reset} {category_str}{service_str}"
        message = entry.message
        
        if entry.error:
            message += f" | Error: {entry.error}"
        
        output = f"{prefix}{message}"
        print(output)
        
        # Print details if verbose
        if self.verbose and entry.details:
            for key, value in entry.details.items():
                print(f"  {key}: {value}")
    
    def error(self, category: LogCategory, message: str, **kwargs) -> LogEntry:
        """Log an error."""
        return self.log(LogLevel.ERROR, category, message, **kwargs)
    
    def warning(self, category: LogCategory, message: str, **kwargs) -> LogEntry:
        """Log a warning."""
        return self.log(LogLevel.WARNING, category, message, **kwargs)
    
    def info(self, category: LogCategory, message: str, **kwargs) -> LogEntry:
        """Log an info message."""
        return self.log(LogLevel.INFO, category, message, **kwargs)
    
    def debug(self, category: LogCategory, message: str, **kwargs) -> LogEntry:
        """Log a debug message."""
        if self.verbose:
            return self.log(LogLevel.DEBUG, category, message, **kwargs)
        return None
    
    def get_startup_errors(self) -> List[LogEntry]:
        """Get all startup errors."""
        return list(self._startup_errors)
    
    def get_startup_warnings(self) -> List[LogEntry]:
        """Get all startup warnings."""
        return list(self._startup_warnings)
    
    def get_test_errors(self) -> List[LogEntry]:
        """Get all test errors."""
        return list(self._test_errors)
    
    def get_test_warnings(self) -> List[LogEntry]:
        """Get all test warnings."""
        return list(self._test_warnings)
    
    def get_health_issues(self) -> List[LogEntry]:
        """Get all health check issues."""
        return list(self._health_issues)
    
    def get_all_errors(self) -> List[LogEntry]:
        """Get all errors across all categories."""
        return self._startup_errors + self._test_errors + self._health_issues
    
    def get_all_warnings(self) -> List[LogEntry]:
        """Get all warnings across all categories."""
        return self._startup_warnings + self._test_warnings
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_entries": len(self.entries),
            "startup_errors": len(self._startup_errors),
            "startup_warnings": len(self._startup_warnings),
            "test_errors": len(self._test_errors),
            "test_warnings": len(self._test_warnings),
            "health_issues": len(self._health_issues),
            "total_errors": len(self.get_all_errors()),
            "total_warnings": len(self.get_all_warnings())
        }
    
    def export_json(self, filename: Optional[str] = None) -> Path:
        """Export all logs to JSON file."""
        if filename is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"orchestration_{timestamp}.json"
        
        filepath = self.log_dir / filename
        
        export_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_summary(),
            "entries": [entry.to_dict() for entry in self.entries],
            "startup_errors": [entry.to_dict() for entry in self._startup_errors],
            "startup_warnings": [entry.to_dict() for entry in self._startup_warnings],
            "test_errors": [entry.to_dict() for entry in self._test_errors],
            "test_warnings": [entry.to_dict() for entry in self._test_warnings],
            "health_issues": [entry.to_dict() for entry in self._health_issues]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        return filepath
    
    def export_text(self, filename: Optional[str] = None, category: Optional[LogCategory] = None) -> Path:
        """Export logs to text file."""
        if filename is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            category_suffix = f"_{category.value}" if category else ""
            filename = f"orchestration{category_suffix}_{timestamp}.log"
        
        filepath = self.log_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for entry in self.entries:
                if category is None or entry.category == category:
                    service_str = f"[{entry.service}] " if entry.service else ""
                    f.write(f"[{entry.timestamp.isoformat()}] [{entry.level.value}] "
                           f"[{entry.category.value}] {service_str}{entry.message}\n")
                    if entry.error:
                        f.write(f"  Error: {entry.error}\n")
                    if entry.details:
                        for key, value in entry.details.items():
                            f.write(f"  {key}: {value}\n")
        
        return filepath
    
    def clear(self):
        """Clear all log entries (for testing or reuse)."""
        self.entries.clear()
        self._startup_errors.clear()
        self._startup_warnings.clear()
        self._test_errors.clear()
        self._test_warnings.clear()
        self._health_issues.clear()

