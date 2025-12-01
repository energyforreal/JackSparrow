"""Final model copy script with full error handling."""
from pathlib import Path
import shutil

source = Path(r"c:\Users\lohit\Downloads\trained_models_20251130_120238")
dest = Path(r"c:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent 2\agent\model_storage\xgboost")

dest.mkdir(parents=True, exist_ok=True)

files = list(source.glob("*.pkl"))
print(f"Source files: {len(files)}")

for f in files:
    dest_file = dest / f.name
    shutil.copy2(f, dest_file)
    print(f"Copied: {f.name} -> {dest_file}")

dest_files = list(dest.glob("*.pkl"))
print(f"Destination files: {len(dest_files)}")
for f in dest_files:
    print(f"  {f.name} ({f.stat().st_size / 1024:.1f} KB)")