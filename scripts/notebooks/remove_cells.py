import json
import sys

# Read notebook
try:
    with open('notebooks/train_btcusd_price_prediction.ipynb', 'r', encoding='utf-8') as f:
        nb = json.load(f)
    sys.stderr.write(f"Loaded notebook with {len(nb['cells'])} cells\n")
except Exception as e:
    sys.stderr.write(f"Error loading notebook: {e}\n")
    sys.exit(1)

# Find and remove cells - be more specific
cells_to_remove = []
for i, cell in enumerate(nb['cells']):
    source = ''.join(cell.get('source', []))
    # Check for the markdown cell
    if 'Train Single Timeframe (Optional)' in source:
        cells_to_remove.append(i)
        sys.stderr.write(f"Found markdown cell {i} to remove\n")
    # Check for the code cell
    elif 'Train single timeframe (XGBoost only)' in source:
        cells_to_remove.append(i)
        sys.stderr.write(f"Found code cell {i} to remove\n")

sys.stderr.write(f"Total cells to remove: {len(cells_to_remove)}\n")

if not cells_to_remove:
    sys.stderr.write("No cells found to remove!\n")
    sys.exit(1)

# Remove cells in reverse order to maintain indices
for idx in reversed(sorted(cells_to_remove)):
    del nb['cells'][idx]
    sys.stderr.write(f"Removed cell {idx}\n")

# Write back
try:
    with open('notebooks/train_btcusd_price_prediction.ipynb', 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    sys.stderr.write(f"Successfully removed {len(cells_to_remove)} cell(s) from notebook\n")
except Exception as e:
    sys.stderr.write(f"Error writing notebook: {e}\n")
    sys.exit(1)
