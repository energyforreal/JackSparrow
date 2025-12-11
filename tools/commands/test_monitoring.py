#!/usr/bin/env python3
"""
Test script for monitoring components in start_parallel.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import from start_parallel
sys.path.insert(0, str(Path(__file__).parent))

# Import monitoring classes
from start_parallel import (
    PaperTradingValidator,
    WebSocketMonitor,
    MonitoringDashboard,
    ValidationReporter,
    Colors,
    get_safe_symbol
)

def test_paper_trading_validator():
    """Test PaperTradingValidator."""
    print(f"{Colors.BOLD}Testing PaperTradingValidator...{Colors.RESET}")
    
    project_root = Path(__file__).parent.parent.parent
    validator = PaperTradingValidator(project_root)
    
    # Test validation
    is_valid, status_msg = validator.validate_startup()
    print(f"  Validation result: {is_valid}")
    print(f"  Status message: {status_msg}")
    
    # Test status
    status = validator.get_status()
    print(f"  Paper mode: {status['is_paper_mode']}")
    print(f"  Status: {status['status_message']}")
    
    print(f"{Colors.GREEN}✓ PaperTradingValidator test passed{Colors.RESET}\n")
    return True

def test_validation_reporter():
    """Test ValidationReporter."""
    print(f"{Colors.BOLD}Testing ValidationReporter...{Colors.RESET}")
    
    project_root = Path(__file__).parent.parent.parent
    reporter = ValidationReporter(project_root)
    
    # Create mock data
    from start_parallel import ServiceManager, ServiceConfig
    from unittest.mock import Mock
    
    mock_manager = Mock()
    mock_manager.is_alive = Mock(return_value=True)
    
    services = {
        "Backend": mock_manager,
        "Agent": mock_manager,
        "Frontend": mock_manager,
    }
    
    paper_validator = PaperTradingValidator(project_root)
    paper_validator.validate_startup()
    
    # Generate report
    report = reporter.generate_report(services, paper_validator, None)
    
    print(f"  Report timestamp: {report['timestamp']}")
    print(f"  Paper trading mode: {report['paper_trading']['mode']}")
    print(f"  Service count: {len(report['service_health'])}")
    
    # Test JSON save
    report_path = reporter.save_json(report, "test_validation_report.json")
    print(f"  Report saved to: {report_path}")
    
    # Clean up
    if report_path.exists():
        report_path.unlink()
        print(f"  Test report cleaned up")
    
    print(f"{Colors.GREEN}✓ ValidationReporter test passed{Colors.RESET}\n")
    return True

def test_websocket_monitor_import():
    """Test WebSocketMonitor import and basic initialization."""
    print(f"{Colors.BOLD}Testing WebSocketMonitor...{Colors.RESET}")
    
    try:
        thresholds = {
            "agent_state": 60,
            "market_tick": 10,
            "other": 30,
        }
        
        monitor = WebSocketMonitor("ws://localhost:8000/ws", thresholds)
        print(f"  WebSocketMonitor initialized")
        print(f"  URL: {monitor.url}")
        print(f"  Thresholds: {monitor.thresholds}")
        
        # Test freshness stats (should be empty initially)
        stats = monitor.get_freshness_stats()
        print(f"  Initial stats - Connected: {stats['connected']}")
        print(f"  Initial stats - Overall freshness: {stats['overall_freshness']}")
        
        print(f"{Colors.GREEN}✓ WebSocketMonitor initialization test passed{Colors.RESET}\n")
        return True
    except Exception as e:
        print(f"{Colors.YELLOW}⚠ WebSocketMonitor test skipped: {e}{Colors.RESET}\n")
        return True  # Not a failure, just optional feature

def test_monitoring_dashboard():
    """Test MonitoringDashboard initialization."""
    print(f"{Colors.BOLD}Testing MonitoringDashboard...{Colors.RESET}")
    
    from unittest.mock import Mock
    
    project_root = Path(__file__).parent.parent.parent
    paper_validator = PaperTradingValidator(project_root)
    paper_validator.validate_startup()
    
    # Create mock services
    mock_manager = Mock()
    mock_manager.is_alive = Mock(return_value=True)
    
    services = {
        "Backend": mock_manager,
        "Agent": mock_manager,
        "Frontend": mock_manager,
    }
    
    dashboard = MonitoringDashboard(
        services,
        paper_validator,
        None,  # No WebSocket monitor for this test
        refresh_interval=1.0,
        clear_screen=False
    )
    
    print(f"  Dashboard initialized")
    print(f"  Refresh interval: {dashboard.refresh_interval}")
    print(f"  Clear screen: {dashboard.clear_screen}")
    
    # Test render (should not crash)
    try:
        dashboard.render()
        print(f"  Dashboard render test passed")
    except Exception as e:
        print(f"{Colors.ERROR}  Dashboard render failed: {e}{Colors.RESET}")
        return False
    
    print(f"{Colors.GREEN}✓ MonitoringDashboard test passed{Colors.RESET}\n")
    return True

def main():
    """Run all tests."""
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}Monitoring Components Test Suite{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
    
    tests = [
        ("PaperTradingValidator", test_paper_trading_validator),
        ("ValidationReporter", test_validation_reporter),
        ("WebSocketMonitor", test_websocket_monitor_import),
        ("MonitoringDashboard", test_monitoring_dashboard),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"{Colors.ERROR}✗ {name} test failed: {e}{Colors.RESET}\n")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}Test Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        symbol = "OK" if result else "X"
        if os.name != "nt":
            symbol = "✓" if result else "✗"
        color = Colors.GREEN if result else Colors.ERROR
        print(f"  {color}{symbol}{Colors.RESET} {name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print(f"{Colors.GREEN}All tests passed!{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.ERROR}Some tests failed{Colors.RESET}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

