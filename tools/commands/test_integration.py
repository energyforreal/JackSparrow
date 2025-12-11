#!/usr/bin/env python3
"""
Integration test for start_parallel.py monitoring features.
Tests that all components work together without actually starting services.
"""

import os
import sys
from pathlib import Path

# Set test environment variables
os.environ["ENABLE_MONITORING_DASHBOARD"] = "false"  # Disable dashboard for testing
os.environ["ENABLE_VALIDATION_REPORT"] = "true"
os.environ["PAPER_TRADING_MODE"] = "true"

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all imports work."""
    print("Testing imports...")
    try:
        from start_parallel import (
            PaperTradingValidator,
            WebSocketMonitor,
            MonitoringDashboard,
            ValidationReporter,
            ParallelProcessManager,
            ServiceManager,
            ServiceConfig,
            Colors
        )
        print("  ✓ All imports successful")
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_paper_trading_validation():
    """Test paper trading validation integration."""
    print("\nTesting paper trading validation...")
    try:
        from start_parallel import PaperTradingValidator
        
        project_root = Path(__file__).parent.parent.parent
        validator = PaperTradingValidator(project_root)
        
        # Test with paper trading enabled
        os.environ["PAPER_TRADING_MODE"] = "true"
        is_valid, status = validator.validate_startup()
        assert is_valid, "Paper trading should be valid"
        assert "PAPER" in status.upper(), "Status should mention paper trading"
        print(f"  ✓ Paper trading validation: {status}")
        
        # Test with live trading (should warn)
        os.environ["PAPER_TRADING_MODE"] = "false"
        validator2 = PaperTradingValidator(project_root)
        is_valid2, status2 = validator2.validate_startup()
        assert not is_valid2, "Live trading should not be valid"
        print(f"  ✓ Live trading detection: {status2}")
        
        # Restore
        os.environ["PAPER_TRADING_MODE"] = "true"
        return True
    except Exception as e:
        print(f"  ✗ Paper trading validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_parallel_process_manager_init():
    """Test ParallelProcessManager initialization."""
    print("\nTesting ParallelProcessManager initialization...")
    try:
        from start_parallel import ParallelProcessManager
        
        project_root = Path(__file__).parent.parent.parent
        manager = ParallelProcessManager(project_root)
        
        assert manager.project_root == project_root
        assert manager.paper_validator is None  # Not initialized yet
        assert manager.ws_monitor is None
        assert manager.dashboard is None
        assert manager.validation_reporter is None
        
        print("  ✓ ParallelProcessManager initialized correctly")
        return True
    except Exception as e:
        print(f"  ✗ ParallelProcessManager initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_service_config():
    """Test ServiceConfig creation."""
    print("\nTesting ServiceConfig...")
    try:
        from start_parallel import ServiceConfig, Colors
        
        config = ServiceConfig(
            name="TestService",
            color=Colors.BACKEND,
            command=["python", "--version"],
            check_delay=1.0
        )
        
        assert config.name == "TestService"
        assert config.color == Colors.BACKEND
        assert len(config.command) == 2
        assert config.check_delay == 1.0
        
        print("  ✓ ServiceConfig created correctly")
        return True
    except Exception as e:
        print(f"  ✗ ServiceConfig test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_validation_reporter_integration():
    """Test ValidationReporter integration."""
    print("\nTesting ValidationReporter integration...")
    try:
        from start_parallel import ValidationReporter, PaperTradingValidator
        from unittest.mock import Mock
        
        project_root = Path(__file__).parent.parent.parent
        reporter = ValidationReporter(project_root)
        validator = PaperTradingValidator(project_root)
        validator.validate_startup()
        
        # Mock services
        mock_manager = Mock()
        mock_manager.is_alive = Mock(return_value=True)
        services = {"Backend": mock_manager, "Agent": mock_manager}
        
        # Generate report
        report = reporter.generate_report(services, validator, None)
        
        assert "timestamp" in report
        assert "paper_trading" in report
        assert "service_health" in report
        assert report["paper_trading"]["mode"] == "paper"
        
        # Save report
        report_path = reporter.save_json(report, "test_integration_report.json")
        assert report_path.exists()
        
        # Clean up
        report_path.unlink()
        
        print("  ✓ ValidationReporter integration test passed")
        return True
    except Exception as e:
        print(f"  ✗ ValidationReporter integration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run integration tests."""
    print("=" * 60)
    print("Integration Test Suite")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Paper Trading Validation", test_paper_trading_validation),
        ("ParallelProcessManager Init", test_parallel_process_manager_init),
        ("ServiceConfig", test_service_config),
        ("ValidationReporter Integration", test_validation_reporter_integration),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("Integration Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        symbol = "✓" if result else "✗"
        print(f"  {symbol} {name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("\n✓ All integration tests passed!")
        return 0
    else:
        print("\n✗ Some integration tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())

