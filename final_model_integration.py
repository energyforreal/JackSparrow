"""Final model integration script - copies models and tests discovery."""
import asyncio
import sys
from pathlib import Path
import shutil

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent.models.model_discovery import ModelDiscovery
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.core.config import settings

output_file = Path("model_integration_report.txt")

def write_log(msg):
    """Write to both stdout and log file."""
    print(msg)
    with open(output_file, "a") as f:
        f.write(msg + "\n")

async def main():
    """Main integration function."""
    with open(output_file, "w") as f:
        f.write("Model Integration Report\n")
        f.write("=" * 60 + "\n\n")
    
    # Step 1: Copy models
    write_log("Step 1: Copying models...")
    source_dir = Path(r"c:\Users\lohit\Downloads\trained_models_20251130_120238")
    dest_dir = Path("agent/model_storage/xgboost")
    
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    model_files = sorted(source_dir.glob("*.pkl"))
    write_log(f"Found {len(model_files)} model files in source")
    
    copied = 0
    for model_file in model_files:
        dest_path = dest_dir / model_file.name
        try:
            shutil.copy2(model_file, dest_path)
            size_kb = dest_path.stat().st_size / 1024
            write_log(f"  ✓ Copied: {model_file.name} ({size_kb:.1f} KB)")
            copied += 1
        except Exception as e:
            write_log(f"  ✗ Failed: {model_file.name} - {e}")
    
    write_log(f"Copied {copied}/{len(model_files)} files\n")
    
    # Step 2: Test discovery
    write_log("Step 2: Testing model discovery...")
    registry = MCPModelRegistry()
    discovery = ModelDiscovery(registry)
    
    discovered = await discovery.discover_models()
    write_log(f"Discovered {len(discovered)} model(s)")
    
    for model_name in sorted(discovered):
        model = registry.get_model(model_name)
        if model:
            write_log(f"  ✓ {model_name} ({model.model_type}, {model.health_status})")
    
    write_log(f"\nIntegration complete!")
    write_log(f"Summary: {copied} files copied, {len(discovered)} models discovered")
    
    return len(discovered) >= 6

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)