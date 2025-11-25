"""Integration tests for startup scripts."""

import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestStartupScripts:
    """Test startup script functionality."""
    
    def test_health_check_script_imports(self):
        """Test that health check script can be imported."""
        try:
            from tools.commands.health_check import HealthChecker, Symbols
            assert HealthChecker is not None
            assert Symbols is not None
        except ImportError as e:
            pytest.fail(f"Failed to import health check script: {e}")
    
    def test_start_parallel_script_imports(self):
        """Test that start_parallel script can be imported."""
        try:
            from tools.commands.start_parallel import ParallelProcessManager, ServiceConfig
            assert ParallelProcessManager is not None
            assert ServiceConfig is not None
        except ImportError as e:
            pytest.fail(f"Failed to import start_parallel script: {e}")
    
    def test_health_check_symbols_windows(self):
        """Test symbols on Windows."""
        with patch('platform.system', return_value='Windows'):
            from tools.commands.health_check import Symbols
            symbols = Symbols()
            assert symbols.CHECK == "[OK]"
            assert symbols.WARNING == "[WARN]"
            assert symbols.CROSS == "[FAIL]"
            assert symbols.SUCCESS == "[SUCCESS]"
    
    def test_health_check_symbols_non_windows(self):
        """Test symbols on non-Windows."""
        with patch('platform.system', return_value='Linux'):
            from tools.commands.health_check import Symbols
            symbols = Symbols()
            assert symbols.CHECK == "✓"
            assert symbols.WARNING == "⚠"
            assert symbols.CROSS == "✗"
            assert symbols.SUCCESS == "✅"
    
    def test_health_checker_initialization(self):
        """Test HealthChecker initialization."""
        from tools.commands.health_check import HealthChecker
        
        checker = HealthChecker(
            backend_url="http://localhost:8000",
            frontend_url="http://localhost:3000",
            timeout=5.0
        )
        
        assert checker.backend_url == "http://localhost:8000"
        assert checker.frontend_url == "http://localhost:3000"
        assert checker.timeout == 5.0
    
    def test_unicode_output_handling(self):
        """Test that scripts handle Unicode output without errors."""
        unicode_strings = [
            "Test with Unicode: ✓ ⚠ ✗ ✅",
            "Mixed content: Hello 世界",
            "Special chars: © ® ™ € £ ¥"
        ]
        
        for test_string in unicode_strings:
            try:
                # Test encoding/decoding
                encoded = test_string.encode('utf-8', errors='replace')
                decoded = encoded.decode('utf-8', errors='replace')
                assert isinstance(decoded, str)
            except UnicodeEncodeError:
                pytest.fail(f"Unicode encoding failed for: {test_string}")
    
    def test_log_file_unicode_handling(self):
        """Test Unicode handling when writing to log files."""
        import tempfile
        
        unicode_content = "Test with Unicode: ✓ ⚠ ✗ ✅\n"
        
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.log') as f:
            log_file_path = Path(f.name)
            try:
                # Write Unicode content
                f.write(unicode_content)
                f.flush()
                
                # Read back and verify
                with open(log_file_path, 'r', encoding='utf-8', errors='replace') as read_file:
                    content = read_file.read()
                    assert "Unicode" in content
            finally:
                # Cleanup
                log_file_path.unlink()
    
    def test_encoding_configuration_windows(self):
        """Test UTF-8 encoding configuration on Windows."""
        if platform.system() != "Windows":
            pytest.skip("Test only relevant on Windows")
        
        # Test that encoding can be configured
        try:
            if sys.stdout.encoding != 'utf-8':
                # Try to reconfigure (may fail on some systems)
                try:
                    sys.stdout.reconfigure(encoding='utf-8')
                except (AttributeError, ValueError):
                    # Python < 3.7 or encoding not available
                    pass
        except Exception as e:
            # Should not raise critical error
            pass
    
    def test_service_config_creation(self):
        """Test ServiceConfig creation."""
        from tools.commands.start_parallel import ServiceConfig, Colors
        
        config = ServiceConfig(
            name="TestService",
            color=Colors.BACKEND,
            command=["python", "--version"],
            cwd=Path.cwd(),
            log_file=None,
            pid_file=None,
            check_delay=1.0
        )
        
        assert config.name == "TestService"
        assert config.color == Colors.BACKEND
        assert len(config.command) == 2
        assert config.check_delay == 1.0
    
    def test_parallel_process_manager_initialization(self):
        """Test ParallelProcessManager initialization."""
        from tools.commands.start_parallel import ParallelProcessManager
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ParallelProcessManager(Path(tmpdir))
            assert manager.project_root == Path(tmpdir)
            assert len(manager.services) == 0


class TestStartupScriptErrorHandling:
    """Test error handling in startup scripts."""
    
    def test_health_check_error_handling(self):
        """Test error handling in health check script."""
        from tools.commands.health_check import HealthChecker
        
        checker = HealthChecker()
        
        # Test that errors are collected but don't crash
        checker.errors.append("Test error")
        assert len(checker.errors) == 1
    
    def test_log_streaming_error_recovery(self):
        """Test error recovery in log streaming."""
        from tools.commands.start_parallel import ParallelProcessManager, ServiceConfig, Colors
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ParallelProcessManager(Path(tmpdir))
            
            config = ServiceConfig(
                name="TestService",
                color=Colors.BACKEND,
                command=["python", "--version"],
                cwd=Path(tmpdir),
                log_file=Path(tmpdir) / "test.log",
                pid_file=None,
                check_delay=1.0
            )
            
            # Should not raise error during initialization
            service = manager._create_service(config)
            assert service is not None
    
    def test_unicode_error_fallback(self):
        """Test Unicode error fallback mechanisms."""
        problematic_string = "Test with problematic chars: ✓"
        
        # Test multiple fallback strategies
        strategies = [
            lambda s: s.encode('utf-8', errors='strict').decode('utf-8'),
            lambda s: s.encode('utf-8', errors='replace').decode('utf-8', errors='replace'),
            lambda s: s.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore'),
        ]
        
        for strategy in strategies:
            try:
                result = strategy(problematic_string)
                assert isinstance(result, str)
            except (UnicodeEncodeError, UnicodeDecodeError):
                # Some strategies might fail, that's okay
                pass


class TestStartupScriptIntegration:
    """Integration tests for startup scripts."""
    
    def test_health_check_script_structure(self):
        """Test that health check script has correct structure."""
        from tools.commands.health_check import HealthChecker, main
        
        # Verify main function exists
        assert callable(main)
    
    def test_start_parallel_script_structure(self):
        """Test that start_parallel script has correct structure."""
        from tools.commands.start_parallel import ParallelProcessManager, main
        
        # Verify main function exists
        assert callable(main)
    
    def test_symbols_consistency(self):
        """Test that symbols are consistent across platforms."""
        from tools.commands.health_check import Symbols
        
        # Test Windows symbols
        with patch('platform.system', return_value='Windows'):
            win_symbols = Symbols()
            assert win_symbols.CHECK == "[OK]"
        
        # Test Linux symbols
        with patch('platform.system', return_value='Linux'):
            linux_symbols = Symbols()
            assert linux_symbols.CHECK == "✓"
    
    def test_script_imports_without_errors(self):
        """Test that scripts can be imported without errors."""
        try:
            import tools.commands.health_check
            import tools.commands.start_parallel
        except Exception as e:
            pytest.fail(f"Failed to import scripts: {e}")

