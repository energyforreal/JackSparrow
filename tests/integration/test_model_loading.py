"""Integration tests for model loading."""

import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

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
from agent.models.xgboost_node import XGBoostNode


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
def valid_xgboost_model(temp_model_dir):
    """Create a valid XGBoost model."""
    if not XGBOOST_AVAILABLE:
        pytest.skip("XGBoost not available")
    
    model_path = temp_model_dir / "valid_model.pkl"
    
    X_train = np.array([[1, 2], [3, 4], [5, 6]])
    y_train = np.array([0, 1, 0])
    
    model = XGBClassifier(n_estimators=2, random_state=42)
    model.fit(X_train, y_train)
    
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    
    return model_path


@pytest.fixture
def corrupted_model(temp_model_dir):
    """Create a corrupted model file."""
    model_path = temp_model_dir / "corrupted_model.pkl"
    with open(model_path, "wb") as f:
        f.write(b"\x0e\x00\x00\x00invalid pickle data")
    return model_path


@pytest.mark.asyncio
async def test_model_discovery_and_loading(temp_model_dir, model_registry, valid_xgboost_model):
    """Test complete model discovery and loading process."""
    # Copy valid model to discovery directory
    discovery_path = temp_model_dir / "test_model.pkl"
    discovery_path.write_bytes(valid_xgboost_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Discover models
        discovered = await discovery.discover_models()
        
        # Verify discovery
        assert len(discovered) == 1
        assert "test_model" in discovered
        
        # Verify model is registered and can be retrieved
        model_node = model_registry.get_model("test_model")
        assert model_node is not None
        assert isinstance(model_node, XGBoostNode)
        assert model_node.health_status == "healthy"


@pytest.mark.asyncio
async def test_model_loading_with_corrupted_files(temp_model_dir, model_registry, valid_xgboost_model, corrupted_model):
    """Test model loading continues when corrupted files are present."""
    # Copy both valid and corrupted models
    valid_path = temp_model_dir / "valid_model.pkl"
    corrupted_path = temp_model_dir / "corrupted_model.pkl"
    
    valid_path.write_bytes(valid_xgboost_model.read_bytes())
    corrupted_path.write_bytes(corrupted_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Discover models
        discovered = await discovery.discover_models()
        
        # Should discover valid model and skip corrupted one
        assert len(discovered) == 1
        assert "valid_model" in discovered
        assert "corrupted_model" not in discovered
        
        # Valid model should be loaded and healthy
        model_node = model_registry.get_model("valid_model")
        assert model_node is not None
        assert model_node.health_status == "healthy"


@pytest.mark.asyncio
async def test_model_prediction_after_loading(temp_model_dir, model_registry, valid_xgboost_model):
    """Test that models can make predictions after loading."""
    discovery_path = temp_model_dir / "test_model.pkl"
    discovery_path.write_bytes(valid_xgboost_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Discover and load model
        await discovery.discover_models()
        
        # Get model and make prediction
        model_node = model_registry.get_model("test_model")
        assert model_node is not None
        
        from agent.models.mcp_model_node import MCPModelRequest
        
        request = MCPModelRequest(
            request_id="test-1",
            features=[1.0, 2.0],
            context={},
            require_explanation=True
        )
        
        prediction = await model_node.predict(request)
        
        # Verify prediction
        assert prediction is not None
        assert -1.0 <= prediction.prediction <= 1.0
        assert 0.0 <= prediction.confidence <= 1.0
        assert prediction.health_status == "healthy"


@pytest.mark.asyncio
async def test_model_discovery_with_model_path(temp_model_dir, model_registry, valid_xgboost_model):
    """Test model discovery with MODEL_PATH set."""
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = str(valid_xgboost_model)
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = valid_xgboost_model
        
        # Discover models
        discovered = await discovery.discover_models()
        
        # Should discover model from MODEL_PATH
        assert len(discovered) == 1
        model_name = valid_xgboost_model.stem
        assert model_name in discovered
        
        # Model should be registered
        model_node = model_registry.get_model(model_name)
        assert model_node is not None
        assert model_node.health_status == "healthy"


@pytest.mark.asyncio
async def test_multiple_models_discovery(temp_model_dir, model_registry, valid_xgboost_model):
    """Test discovering multiple valid models."""
    # Create multiple valid models
    for i in range(3):
        model_path = temp_model_dir / f"model_{i}.pkl"
        model_path.write_bytes(valid_xgboost_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Discover models
        discovered = await discovery.discover_models()
        
        # Should discover all models
        assert len(discovered) == 3
        assert all(f"model_{i}" in discovered for i in range(3))
        
        # All models should be registered and healthy
        for i in range(3):
            model_node = model_registry.get_model(f"model_{i}")
            assert model_node is not None
            assert model_node.health_status == "healthy"


@pytest.mark.asyncio
async def test_model_discovery_graceful_failure(temp_model_dir, model_registry, corrupted_model):
    """Test that model discovery handles failures gracefully."""
    # Create only corrupted models
    corrupted_path = temp_model_dir / "corrupted_model.pkl"
    corrupted_path.write_bytes(corrupted_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Should not raise exception, just return empty list
        discovered = await discovery.discover_models()
        
        # Should return empty list but not crash
        assert len(discovered) == 0
        assert len(model_registry.list_models()) == 0


@pytest.mark.asyncio
async def test_model_registry_operations(temp_model_dir, model_registry, valid_xgboost_model):
    """Test model registry operations after discovery."""
    discovery_path = temp_model_dir / "test_model.pkl"
    discovery_path.write_bytes(valid_xgboost_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Discover models
        await discovery.discover_models()
        
        # Test registry operations
        models = model_registry.list_models()
        assert len(models) == 1
        assert "test_model" in models
        
        model_node = model_registry.get_model("test_model")
        assert model_node is not None
        
        # Test getting non-existent model
        assert model_registry.get_model("nonexistent") is None


@pytest.mark.asyncio
async def test_model_health_status_after_loading(temp_model_dir, model_registry, valid_xgboost_model):
    """Test model health status after loading."""
    discovery_path = temp_model_dir / "test_model.pkl"
    discovery_path.write_bytes(valid_xgboost_model.read_bytes())
    
    with patch('agent.models.model_discovery.settings') as mock_settings:
        mock_settings.model_dir = str(temp_model_dir)
        mock_settings.model_path = None
        mock_settings.model_discovery_enabled = True
        
        discovery = ModelDiscovery(model_registry)
        discovery.model_dir = temp_model_dir
        discovery.model_path = None
        
        # Discover models
        await discovery.discover_models()
        
        # Get model and check health
        model_node = model_registry.get_model("test_model")
        assert model_node is not None
        
        health = await model_node.get_health_status()
        assert health["status"] == "healthy"
        assert health["model_loaded"] is True
        
        # Model info should be available
        info = model_node.get_model_info()
        assert info["health_status"] == "healthy"
        assert info["model_name"] == "test_model"

