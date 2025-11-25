"""Unit tests for model discovery."""

import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import numpy as np

# Provide minimal config so agent settings can initialize during tests
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("MODEL_DIR", "./test_models")
os.environ.setdefault("MODEL_PATH", "")

try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry


@pytest.fixture
def temp_model_dir():
    """Create temporary directory for test model files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def model_registry():
    """Create model registry instance."""
    return MCPModelRegistry()


@pytest.fixture
def valid_xgboost_model_file(temp_model_dir):
    """Create a valid XGBoost model file."""
    if not XGBOOST_AVAILABLE:
        pytest.skip("XGBoost not available")
    
    model_path = temp_model_dir / "valid_model.pkl"
    
    # Create a simple XGBoost model
    X_train = np.array([[1, 2], [3, 4], [5, 6]])
    y_train = np.array([0, 1, 0])
    
    model = XGBClassifier(n_estimators=2, random_state=42)
    model.fit(X_train, y_train)
    
    # Save model
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    
    return model_path


@pytest.fixture
def corrupted_model_file(temp_model_dir):
    """Create a corrupted model file."""
    model_path = temp_model_dir / "corrupted_model.pkl"
    # Write invalid pickle data
    with open(model_path, "wb") as f:
        f.write(b"\x0e\x00\x00\x00invalid pickle data")
    return model_path


@pytest.fixture
def empty_model_file(temp_model_dir):
    """Create an empty model file."""
    model_path = temp_model_dir / "empty_model.pkl"
    model_path.touch()
    return model_path


@pytest.fixture
def invalid_format_file(temp_model_dir):
    """Create a file with invalid format."""
    model_path = temp_model_dir / "invalid_format.pkl"
    with open(model_path, "wb") as f:
        f.write(b"NOT_A_PICKLE_FILE")
    return model_path


@pytest.fixture
def model_discovery(model_registry, temp_model_dir):
    """Create model discovery instance with temp directory."""
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        return discovery


@pytest.mark.asyncio
async def test_discover_valid_model(model_discovery, model_registry, valid_xgboost_model_file):
    """Test discovering a valid model."""
    # Copy valid model to discovery directory
    discovery_path = model_discovery.model_dir / "valid_model.pkl"
    discovery_path.write_bytes(valid_xgboost_model_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    assert len(discovered) == 1
    assert "valid_model" in discovered
    assert model_registry.get_model("valid_model") is not None


@pytest.mark.asyncio
async def test_discover_with_corrupted_file(model_discovery, model_registry, valid_xgboost_model_file, corrupted_model_file):
    """Test that discovery continues when encountering corrupted files."""
    # Copy both valid and corrupted models
    valid_path = model_discovery.model_dir / "valid_model.pkl"
    corrupted_path = model_discovery.model_dir / "corrupted_model.pkl"
    
    valid_path.write_bytes(valid_xgboost_model_file.read_bytes())
    corrupted_path.write_bytes(corrupted_model_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    # Should discover valid model and skip corrupted one
    assert len(discovered) == 1
    assert "valid_model" in discovered
    assert "corrupted_model" not in discovered
    # Discovery should continue despite corrupted file
    assert model_registry.get_model("valid_model") is not None


@pytest.mark.asyncio
async def test_discover_with_empty_file(model_discovery, model_registry, valid_xgboost_model_file, empty_model_file):
    """Test that discovery continues when encountering empty files."""
    valid_path = model_discovery.model_dir / "valid_model.pkl"
    empty_path = model_discovery.model_dir / "empty_model.pkl"
    
    valid_path.write_bytes(valid_xgboost_model_file.read_bytes())
    empty_path.write_bytes(empty_model_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    # Should discover valid model and skip empty one
    assert len(discovered) == 1
    assert "valid_model" in discovered
    assert "empty_model" not in discovered


@pytest.mark.asyncio
async def test_discover_with_invalid_format(model_discovery, model_registry, valid_xgboost_model_file, invalid_format_file):
    """Test that discovery continues when encountering invalid format files."""
    valid_path = model_discovery.model_dir / "valid_model.pkl"
    invalid_path = model_discovery.model_dir / "invalid_format.pkl"
    
    valid_path.write_bytes(valid_xgboost_model_file.read_bytes())
    invalid_path.write_bytes(invalid_format_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    # Should discover valid model and skip invalid format one
    assert len(discovered) == 1
    assert "valid_model" in discovered
    assert "invalid_format" not in discovered


@pytest.mark.asyncio
async def test_discover_multiple_corrupted_files(model_discovery, model_registry, valid_xgboost_model_file):
    """Test that discovery continues with multiple corrupted files."""
    # Create multiple corrupted files
    valid_path = model_discovery.model_dir / "valid_model.pkl"
    valid_path.write_bytes(valid_xgboost_model_file.read_bytes())
    
    # Create multiple corrupted files
    for i in range(3):
        corrupted_path = model_discovery.model_dir / f"corrupted_{i}.pkl"
        with open(corrupted_path, "wb") as f:
            f.write(b"\x0e\x00\x00\x00invalid pickle data")
    
    discovered = await model_discovery.discover_models()
    
    # Should still discover valid model
    assert len(discovered) == 1
    assert "valid_model" in discovered


@pytest.mark.asyncio
async def test_discover_all_corrupted_files(model_discovery, model_registry, corrupted_model_file):
    """Test discovery when all files are corrupted."""
    # Create multiple corrupted files
    for i in range(3):
        corrupted_path = model_discovery.model_dir / f"corrupted_{i}.pkl"
        corrupted_path.write_bytes(corrupted_model_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    # Should return empty list but not crash
    assert len(discovered) == 0
    assert len(model_registry.list_models()) == 0


@pytest.mark.asyncio
async def test_discover_mixed_valid_and_corrupted(model_discovery, model_registry, valid_xgboost_model_file, corrupted_model_file):
    """Test discovery with mix of valid and corrupted files."""
    # Create mix of files
    files = [
        ("valid1.pkl", valid_xgboost_model_file),
        ("corrupted1.pkl", corrupted_model_file),
        ("valid2.pkl", valid_xgboost_model_file),
        ("corrupted2.pkl", corrupted_model_file),
    ]
    
    for filename, source_file in files:
        dest_path = model_discovery.model_dir / filename
        dest_path.write_bytes(source_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    # Should discover only valid models
    assert len(discovered) == 2
    assert "valid1" in discovered
    assert "valid2" in discovered
    assert "corrupted1" not in discovered
    assert "corrupted2" not in discovered


@pytest.mark.asyncio
async def test_discover_error_categorization(model_discovery, model_registry, corrupted_model_file):
    """Test that errors are properly categorized."""
    corrupted_path = model_discovery.model_dir / "corrupted_model.pkl"
    corrupted_path.write_bytes(corrupted_model_file.read_bytes())
    
    # Mock logger to capture error logs
    error_logs = []
    
    def capture_error(*args, **kwargs):
        if "model_discovery_corrupted_file" in kwargs.get("event", ""):
            error_logs.append(kwargs)
    
    with patch('agent.models.model_discovery.logger.error', side_effect=capture_error):
        await model_discovery.discover_models()
    
    # Should log corrupted file error
    assert len(error_logs) > 0
    assert any("corrupted" in str(log.get("message", "")).lower() for log in error_logs)


@pytest.mark.asyncio
async def test_discover_graceful_skip_corrupted(model_discovery, model_registry, valid_xgboost_model_file, corrupted_model_file):
    """Test that corrupted files are gracefully skipped."""
    valid_path = model_discovery.model_dir / "valid_model.pkl"
    corrupted_path = model_discovery.model_dir / "corrupted_model.pkl"
    
    valid_path.write_bytes(valid_xgboost_model_file.read_bytes())
    corrupted_path.write_bytes(corrupted_model_file.read_bytes())
    
    # Should not raise exception
    discovered = await model_discovery.discover_models()
    
    # Should discover valid model
    assert len(discovered) == 1
    assert "valid_model" in discovered


@pytest.mark.asyncio
async def test_discover_continues_after_error(model_discovery, model_registry, valid_xgboost_model_file, corrupted_model_file):
    """Test that discovery continues after encountering errors."""
    # Create files in order: corrupted, valid, corrupted
    files = [
        ("corrupted1.pkl", corrupted_model_file),
        ("valid_model.pkl", valid_xgboost_model_file),
        ("corrupted2.pkl", corrupted_model_file),
    ]
    
    for filename, source_file in files:
        dest_path = model_discovery.model_dir / filename
        dest_path.write_bytes(source_file.read_bytes())
    
    discovered = await model_discovery.discover_models()
    
    # Should discover valid model despite errors before and after
    assert len(discovered) == 1
    assert "valid_model" in discovered


@pytest.mark.asyncio
async def test_discover_with_model_path(model_registry, valid_xgboost_model_file, temp_model_dir):
    """Test discovery with MODEL_PATH set."""
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = str(valid_xgboost_model_file)
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = valid_xgboost_model_file
        
        discovered = await discovery.discover_models()
        
        # Should discover model from MODEL_PATH
        assert len(discovered) == 1
        assert model_registry.get_model(valid_xgboost_model_file.stem) is not None


@pytest.mark.asyncio
async def test_discover_empty_directory(model_discovery, model_registry):
    """Test discovery with empty directory."""
    discovered = await model_discovery.discover_models()
    
    # Should return empty list but not crash
    assert len(discovered) == 0
    assert len(model_registry.list_models()) == 0


@pytest.mark.asyncio
async def test_discover_nonexistent_directory(model_registry):
    """Test discovery with non-existent directory."""
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = "/nonexistent/directory"
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = Path("/nonexistent/directory")
        discovery.model_path = None
        
        # Should handle gracefully
        discovered = await discovery.discover_models()
        
        # Should return empty list but not crash
        assert len(discovered) == 0

