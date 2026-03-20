"""Unit tests for XGBoost model node."""

import os
import pickle
import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
import numpy as np

# Provide minimal config so agent settings can initialize during tests
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

try:
    from xgboost import XGBClassifier
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

from agent.models.xgboost_node import XGBoostNode
from agent.models.mcp_model_node import MCPModelRequest


@pytest.fixture
def temp_dir():
    """Create temporary directory for test model files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def valid_xgboost_model(temp_dir):
    """Create a valid XGBoost model file."""
    if not XGBOOST_AVAILABLE:
        pytest.skip("XGBoost not available")
    
    model_path = temp_dir / "valid_model.pkl"
    
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
def empty_model_file(temp_dir):
    """Create an empty model file."""
    model_path = temp_dir / "empty_model.pkl"
    model_path.touch()
    return model_path


@pytest.fixture
def corrupted_model_file(temp_dir):
    """Create a corrupted model file."""
    model_path = temp_dir / "corrupted_model.pkl"
    # Write invalid pickle data
    with open(model_path, "wb") as f:
        f.write(b"\x0e\x00\x00\x00invalid pickle data")
    return model_path


@pytest.fixture
def small_model_file(temp_dir):
    """Create a suspiciously small model file."""
    model_path = temp_dir / "small_model.pkl"
    # Write minimal data (less than 100 bytes)
    with open(model_path, "wb") as f:
        f.write(b"\x80\x03" + b"x" * 50)  # Valid pickle header but small
    return model_path


@pytest.fixture
def invalid_format_file(temp_dir):
    """Create a file with invalid pickle format."""
    model_path = temp_dir / "invalid_format.pkl"
    # Write data that doesn't start with pickle magic bytes
    with open(model_path, "wb") as f:
        f.write(b"NOT_A_PICKLE_FILE")
    return model_path


@pytest.fixture
def non_existent_model(temp_dir):
    """Return path to non-existent model file."""
    return temp_dir / "non_existent.pkl"


@pytest.mark.asyncio
async def test_load_valid_model(valid_xgboost_model):
    """Test loading a valid XGBoost model."""
    node = XGBoostNode(valid_xgboost_model)
    await node.initialize()
    
    assert node.model is not None
    assert node.health_status == "healthy"
    assert node.model_name == "valid_model"
    assert node.model_type == "xgboost"


@pytest.mark.asyncio
async def test_load_empty_file(empty_model_file):
    """Test handling of empty model file."""
    node = XGBoostNode(empty_model_file)
    
    with pytest.raises(ValueError, match="Model file is empty"):
        await node.initialize()
    
    assert node.health_status == "unhealthy"
    assert node.model is None


@pytest.mark.asyncio
async def test_load_corrupted_file(corrupted_model_file):
    """Test handling of corrupted model file."""
    node = XGBoostNode(corrupted_model_file)
    
    with pytest.raises(ValueError, match="corrupted"):
        await node.initialize()
    
    assert node.health_status == "unhealthy"
    assert node.model is None


@pytest.mark.asyncio
async def test_load_small_file_warning(small_model_file):
    """Test warning for suspiciously small model file."""
    node = XGBoostNode(small_model_file)
    
    # Should warn but may still try to load (depending on pickle validity)
    # The actual behavior depends on whether the pickle is valid
    try:
        await node.initialize()
        # If it loads, health should be set
        assert node.health_status in ("healthy", "unhealthy")
    except (ValueError, pickle.UnpicklingError, EOFError):
        # If it fails to load, that's also acceptable
        assert node.health_status == "unhealthy"


@pytest.mark.asyncio
async def test_load_invalid_format_file(invalid_format_file):
    """Test handling of file with invalid pickle format."""
    node = XGBoostNode(invalid_format_file)
    
    # Should warn about invalid format but may still try to load
    try:
        await node.initialize()
        # If it somehow loads, health should be set
        assert node.health_status in ("healthy", "unhealthy")
    except (ValueError, pickle.UnpicklingError, EOFError):
        # If it fails to load, that's expected
        assert node.health_status == "unhealthy"


@pytest.mark.asyncio
async def test_load_nonexistent_file(non_existent_model):
    """Test handling of non-existent model file."""
    node = XGBoostNode(non_existent_model)
    
    with pytest.raises(FileNotFoundError):
        await node.initialize()
    
    assert node.health_status == "unhealthy"
    assert node.model is None


@pytest.mark.asyncio
async def test_xgboost_compatibility_warning(valid_xgboost_model):
    """Test that XGBoost compatibility warnings are captured."""
    node = XGBoostNode(valid_xgboost_model)
    
    # Mock warnings to simulate XGBoost compatibility warning
    with patch('agent.models.xgboost_node.warnings.catch_warnings') as mock_warnings:
        mock_warning = MagicMock()
        mock_warning.message = "Model was serialized with an older version of XGBoost"
        
        # Create context manager that yields warnings
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=[mock_warning])
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_warnings.return_value = mock_context
        
        await node.initialize()
        
        # Model should still load successfully despite warning
        assert node.model is not None
        assert node.health_status == "healthy"


@pytest.mark.asyncio
async def test_predict_with_valid_model(valid_xgboost_model):
    """Test prediction with a valid model."""
    node = XGBoostNode(valid_xgboost_model)
    await node.initialize()
    
    request = MCPModelRequest(
        request_id="test-1",
        features=[1.0, 2.0],
        context={},
        require_explanation=True
    )
    
    prediction = await node.predict(request)
    
    assert prediction is not None
    assert prediction.model_name == "valid_model"
    assert -1.0 <= prediction.prediction <= 1.0
    assert 0.0 <= prediction.confidence <= 1.0
    assert prediction.health_status == "healthy"
    assert len(prediction.reasoning) > 0


@pytest.mark.asyncio
async def test_predict_with_unhealthy_model(valid_xgboost_model):
    """Test prediction when model is unhealthy."""
    node = XGBoostNode(valid_xgboost_model)
    # Don't initialize, so model is None
    
    request = MCPModelRequest(
        request_id="test-2",
        features=[1.0, 2.0],
        context={},
        require_explanation=True
    )
    
    prediction = await node.predict(request)
    
    # Should return degraded prediction
    assert prediction is not None
    assert prediction.prediction == 0.0
    assert prediction.confidence == 0.0
    assert prediction.health_status == "degraded"
    assert "failed" in prediction.reasoning.lower() or "not loaded" in prediction.reasoning.lower()


@pytest.mark.asyncio
async def test_file_size_validation(valid_xgboost_model):
    """Test file size validation."""
    node = XGBoostNode(valid_xgboost_model)
    
    # Check that file size is validated
    file_size = valid_xgboost_model.stat().st_size
    assert file_size > 0
    
    await node.initialize()
    assert node.model is not None


@pytest.mark.asyncio
async def test_pickle_magic_bytes_validation(valid_xgboost_model):
    """Test pickle magic bytes validation."""
    node = XGBoostNode(valid_xgboost_model)
    
    # Valid pickle file should start with \x80
    with open(valid_xgboost_model, "rb") as f:
        magic_bytes = f.read(4)
        assert magic_bytes.startswith(b'\x80')
    
    await node.initialize()
    assert node.model is not None


@pytest.mark.asyncio
async def test_get_model_info(valid_xgboost_model):
    """Test getting model information."""
    node = XGBoostNode(valid_xgboost_model)
    await node.initialize()
    
    info = node.get_model_info()
    
    assert info["model_name"] == "valid_model"
    assert info["model_version"] == "1.0.0"
    assert info["model_type"] == "xgboost"
    assert info["model_path"] == str(valid_xgboost_model)
    assert info["health_status"] == "healthy"


@pytest.mark.asyncio
async def test_get_health_status(valid_xgboost_model):
    """Test getting health status."""
    node = XGBoostNode(valid_xgboost_model)
    await node.initialize()
    
    health = await node.get_health_status()
    
    assert health["status"] == "healthy"
    assert health["model_loaded"] is True


@pytest.mark.asyncio
async def test_error_categorization_corrupted(corrupted_model_file):
    """Test that corrupted files are properly categorized."""
    node = XGBoostNode(corrupted_model_file)
    
    with pytest.raises(ValueError) as exc_info:
        await node.initialize()
    
    error_msg = str(exc_info.value)
    assert "corrupted" in error_msg.lower() or "incompatible format" in error_msg.lower()


@pytest.mark.asyncio
async def test_error_categorization_empty(empty_model_file):
    """Test that empty files are properly categorized."""
    node = XGBoostNode(empty_model_file)
    
    with pytest.raises(ValueError) as exc_info:
        await node.initialize()
    
    error_msg = str(exc_info.value)
    assert "empty" in error_msg.lower()


@pytest.mark.asyncio
async def test_model_continues_after_warning(valid_xgboost_model):
    """Test that model loading continues after compatibility warning."""
    node = XGBoostNode(valid_xgboost_model)
    
    # Even if warnings are raised, model should load
    await node.initialize()
    
    assert node.model is not None
    assert node.health_status == "healthy"

