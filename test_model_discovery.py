"""Test model discovery to verify all models are found."""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.core.config import settings

async def test_discovery():
    """Test model discovery."""
    print("=" * 60)
    print("Testing Model Discovery")
    print("=" * 60)
    print()
    print(f"MODEL_DIR: {settings.model_dir}")
    print(f"MODEL_PATH: {settings.model_path}")
    print(f"MODEL_DISCOVERY_ENABLED: {settings.model_discovery_enabled}")
    print(f"MODEL_AUTO_REGISTER: {settings.model_auto_register}")
    print()
    
    registry = MCPModelRegistry()
    discovery = ModelDiscovery(registry)
    
    print("Starting model discovery...")
    discovered_models = await discovery.discover_models()
    
    print()
    print("=" * 60)
    print("Discovery Results")
    print("=" * 60)
    print(f"Discovered {len(discovered_models)} model(s)")
    print()
    
    if discovered_models:
        print("Discovered models:")
        for model_name in sorted(discovered_models):
            model = registry.get_model(model_name)
            if model:
                print(f"  ✓ {model_name}")
                print(f"    - Type: {model.model_type}")
                print(f"    - Version: {model.model_version}")
                print(f"    - Health: {model.health_status}")
            else:
                print(f"  ? {model_name} (registered but not found in registry)")
    else:
        print("⚠️  No models discovered!")
        print()
        print("Check:")
        print(f"  1. MODEL_DIR exists: {Path(settings.model_dir).exists()}")
        print(f"  2. Model files exist in {settings.model_dir}")
        
        # Check for model files
        model_dir = Path(settings.model_dir)
        if model_dir.exists():
            pkl_files = list(model_dir.rglob("*.pkl"))
            print(f"  3. Found {len(pkl_files)} .pkl files in MODEL_DIR:")
            for f in pkl_files[:10]:
                print(f"     - {f.relative_to(project_root)}")
    
    print()
    discovery_summary = registry.get_discovery_summary()
    print("Discovery Summary:")
    print(f"  - Attempted: {discovery_summary.get('discovery_attempted', False)}")
    print(f"  - Discovered: {discovery_summary.get('discovered_models', 0)}")
    print(f"  - Failed: {discovery_summary.get('failed_models', 0)}")
    
    return len(discovered_models) > 0

if __name__ == "__main__":
    success = asyncio.run(test_discovery())
    sys.exit(0 if success else 1)