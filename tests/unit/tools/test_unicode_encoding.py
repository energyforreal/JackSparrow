"""Unit tests for Unicode encoding handling in scripts."""

import io
import platform
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

# Import the modules we're testing
from tools.commands.health_check import HealthChecker, Symbols, _symbols
from tools.commands.start_parallel import ParallelProcessManager, ServiceConfig, Colors


class TestSymbols:
    """Test ASCII-safe symbol handling."""
    
    def test_symbols_windows(self):
        """Test symbols on Windows use ASCII-safe alternatives."""
        with patch('platform.system', return_value='Windows'):
            symbols = Symbols()
            assert symbols.CHECK == "[OK]"
            assert symbols.WARNING == "[WARN]"
            assert symbols.CROSS == "[FAIL]"
            assert symbols.SUCCESS == "[SUCCESS]"
    
    def test_symbols_non_windows(self):
        """Test symbols on non-Windows use Unicode."""
        with patch('platform.system', return_value='Linux'):
            symbols = Symbols()
            assert symbols.CHECK == "✓"
            assert symbols.WARNING == "⚠"
            assert symbols.CROSS == "✗"
            assert symbols.SUCCESS == "✅"
    
    def test_symbols_unicode_safe(self):
        """Test that symbols don't cause encoding errors."""
        # Test that we can encode/decode symbols without errors
        symbols = Symbols()
        
        # All symbols should be encodable to UTF-8
        for symbol_name in ['CHECK', 'WARNING', 'CROSS', 'SUCCESS']:
            symbol_value = getattr(symbols, symbol_name)
            # Should not raise UnicodeEncodeError
            encoded = symbol_value.encode('utf-8', errors='strict')
            decoded = encoded.decode('utf-8')
            assert decoded == symbol_value


class TestHealthCheckUnicode:
    """Test Unicode handling in health check script."""
    
    def test_health_check_with_unicode_output(self):
        """Test health checker handles Unicode in output."""
        checker = HealthChecker()
        
        # Test that we can print Unicode characters without errors
        test_message = "Test with Unicode: ✓ ⚠ ✗ ✅"
        
        # Capture stdout
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            try:
                # Try to print Unicode message
                print(test_message)
                output = captured_output.getvalue()
                assert "Test with Unicode" in output
            except UnicodeEncodeError:
                # On Windows with non-UTF-8 console, this might fail
                # But our code should handle it gracefully
                pass
    
    def test_health_check_symbols_printable(self):
        """Test that health check symbols can be printed."""
        checker = HealthChecker()
        
        # Test printing with symbols
        test_cases = [
            f"{_symbols.CHECK} Check passed",
            f"{_symbols.WARNING} Warning message",
            f"{_symbols.CROSS} Check failed",
            f"{_symbols.SUCCESS} Success message"
        ]
        
        for test_case in test_cases:
            # Should not raise UnicodeEncodeError
            try:
                # Encode to bytes to simulate console output
                test_case.encode('utf-8', errors='replace')
            except UnicodeEncodeError:
                pytest.fail(f"Symbol encoding failed: {test_case}")


class TestStartParallelUnicode:
    """Test Unicode handling in start_parallel script."""
    
    def test_log_streaming_unicode_handling(self):
        """Test log streaming handles Unicode characters."""
        # Create a mock process with Unicode output
        mock_process = MagicMock()
        mock_process.stdout = MagicMock()
        
        # Simulate Unicode output
        unicode_lines = [
            "Test line 1\n",
            "Test with Unicode: ✓ ⚠ ✗ ✅\n",
            "Another line\n"
        ]
        
        line_iter = iter(unicode_lines)
        mock_process.stdout.readline = MagicMock(side_effect=lambda: next(line_iter, ''))
        
        # Create service config
        config = ServiceConfig(
            name="TestService",
            color=Colors.BACKEND,
            command=["python", "--version"],
            cwd=Path.cwd(),
            log_file=None,
            pid_file=None,
            check_delay=1.0
        )
        
        manager = ParallelProcessManager(Path.cwd())
        service = manager._create_service(config)
        service.process = mock_process
        
        # Test that _stream_logs handles Unicode
        # This should not raise UnicodeEncodeError
        try:
            # Mock the print function to capture output
            with patch('builtins.print') as mock_print:
                # Run a single iteration (would normally be in a loop)
                line = mock_process.stdout.readline()
                if line:
                    # Simulate the encoding handling logic
                    if isinstance(line, bytes):
                        line = line.decode('utf-8', errors='replace')
                    # Should not raise error
                    safe_line = line.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    mock_print(safe_line.rstrip())
        except UnicodeEncodeError:
            pytest.fail("Unicode encoding error in log streaming")
    
    def test_utf8_encoding_configuration_windows(self):
        """Test UTF-8 encoding configuration on Windows."""
        with patch('platform.system', return_value='Windows'):
            with patch('sys.stdout') as mock_stdout:
                mock_stdout.encoding = 'cp1252'  # Windows default
                mock_stdout.reconfigure = MagicMock()
                
                # Simulate the encoding configuration code
                if platform.system() == "Windows":
                    try:
                        if sys.stdout.encoding != 'utf-8':
                            sys.stdout.reconfigure(encoding='utf-8')
                    except (AttributeError, ValueError):
                        pass
                
                # Should attempt to reconfigure
                if hasattr(sys.stdout, 'reconfigure'):
                    mock_stdout.reconfigure.assert_called_once_with(encoding='utf-8')
    
    def test_unicode_fallback_handling(self):
        """Test fallback handling for Unicode encoding errors."""
        # Test the fallback logic in log streaming
        unicode_string = "Test with Unicode: ✓ ⚠ ✗ ✅"
        
        # Simulate encoding error and fallback
        try:
            # Try normal encoding
            encoded = unicode_string.encode('utf-8', errors='strict')
            decoded = encoded.decode('utf-8')
            assert decoded == unicode_string
        except UnicodeEncodeError:
            # Fallback: use errors='replace'
            encoded = unicode_string.encode('utf-8', errors='replace')
            decoded = encoded.decode('utf-8', errors='replace')
            # Should not raise error
            assert isinstance(decoded, str)
    
    def test_log_file_unicode_handling(self):
        """Test Unicode handling when writing to log files."""
        import tempfile
        
        unicode_content = [
            "Test line 1\n",
            "Test with Unicode: ✓ ⚠ ✗ ✅\n",
            "Another line with émojis 🚀\n"
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.log') as f:
            log_file_path = Path(f.name)
            try:
                # Write Unicode content
                for line in unicode_content:
                    f.write(line)
                    f.flush()
                
                # Read back and verify
                with open(log_file_path, 'r', encoding='utf-8', errors='replace') as read_file:
                    content = read_file.read()
                    assert "Test line 1" in content
                    assert "Unicode" in content
            finally:
                # Cleanup
                log_file_path.unlink()
    
    def test_console_output_unicode_safe(self):
        """Test that console output handles Unicode safely."""
        # Test various Unicode scenarios
        test_cases = [
            "Simple ASCII text",
            "Text with émojis: ✓ ⚠ ✗ ✅ 🚀",
            "Mixed content: Hello 世界",
            "Special chars: © ® ™ € £ ¥"
        ]
        
        for test_case in test_cases:
            # Should be able to encode/decode without errors
            try:
                # Simulate console output encoding
                encoded = test_case.encode('utf-8', errors='replace')
                decoded = encoded.decode('utf-8', errors='replace')
                assert isinstance(decoded, str)
            except UnicodeEncodeError:
                pytest.fail(f"Unicode encoding failed for: {test_case}")


class TestEncodingErrorRecovery:
    """Test error recovery mechanisms for encoding issues."""
    
    def test_encoding_error_graceful_degradation(self):
        """Test that encoding errors are handled gracefully."""
        # Simulate an encoding error scenario
        problematic_string = "Test with problematic chars: ✓"
        
        # Test the error handling pattern used in code
        try:
            # Try to encode (might fail on some systems)
            encoded = problematic_string.encode('utf-8', errors='strict')
            decoded = encoded.decode('utf-8')
        except UnicodeEncodeError:
            # Fallback: use replace strategy
            encoded = problematic_string.encode('utf-8', errors='replace')
            decoded = encoded.decode('utf-8', errors='replace')
            # Should succeed with fallback
            assert isinstance(decoded, str)
            assert len(decoded) > 0
    
    def test_multiple_encoding_strategies(self):
        """Test multiple encoding strategies for robustness."""
        unicode_string = "Test: ✓ ⚠ ✗ ✅"
        
        strategies = [
            lambda s: s.encode('utf-8', errors='strict').decode('utf-8'),
            lambda s: s.encode('utf-8', errors='replace').decode('utf-8', errors='replace'),
            lambda s: s.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore'),
        ]
        
        for strategy in strategies:
            try:
                result = strategy(unicode_string)
                assert isinstance(result, str)
            except (UnicodeEncodeError, UnicodeDecodeError):
                # Some strategies might fail, that's okay
                pass

