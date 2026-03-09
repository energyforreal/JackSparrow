"""Patch JackSparrow notebook for dynamic root and xgboost MODEL_DIR."""
import json
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "notebooks" / "JackSparrow_Trading_Colab_v3.ipynb"
with open(p, encoding="utf-8") as f:
    nb = json.load(f)

for i, c in enumerate(nb["cells"]):
    if c.get("cell_type") != "code":
        continue
    src = "".join(c.get("source", []))
    if "1.2  Project directory structure" not in src:
        continue
    if "get_project_root" in src:
        print("Cell already patched (get_project_root present), skipping path patch.")
        break
    if "BASE   = Path" not in src:
        continue
    new = src.replace(
        "BASE   = Path('/content/trading-agent') if IN_COLAB else Path('.')",
        """try:
    import sys
    _cwd = Path('.').resolve()
    if str(_cwd) not in sys.path:
        sys.path.insert(0, str(_cwd))
    from config.paths import get_project_root
    BASE = get_project_root()
except ImportError:
    BASE = Path('/content/trading-agent') if IN_COLAB else Path('.').resolve()""",
    )
    new = new.replace(
        "    BASE / 'agent' / 'model_storage' / 'robust_ensemble',",
        "    BASE / 'agent' / 'model_storage' / 'xgboost',\n    BASE / 'agent' / 'model_storage' / 'robust_ensemble',",
    )
    new = new.replace(
        "MODEL_DIR = BASE / 'agent' / 'model_storage' / 'robust_ensemble'",
        "MODEL_DIR = BASE / 'agent' / 'model_storage' / 'xgboost'",
    )
    new = new.replace(
        "print('Project layout:')",
        "print('Project layout (BASE =', BASE, '):')",
    )
    c["source"] = [line + "\n" for line in new.rstrip().split("\n")]
    if not c["source"][-1].endswith("\n"):
        c["source"][-1] += "\n"
    print("Updated cell", i)
    break
else:
    print("Path cell not found or already patched.")

# Add optional "Run training scripts" cell after 12 — Export (once)
has_run_cell = any("12.0  (Optional) Run project training scripts" in "".join(c.get("source", [])) for c in nb["cells"])
if not has_run_cell:
    for idx, c in enumerate(nb["cells"]):
        src = "".join(c.get("source", []))
        if "## 12 " in src and "Export" in src and c.get("cell_type") == "markdown":
            run_cell = {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# —— 12.0  (Optional) Run project training scripts ——\n",
                "# Exports to agent/model_storage/xgboost with strict artifacts.\n",
                "import subprocess, sys, os\n",
                "out_dir = str(BASE / 'agent' / 'model_storage')\n",
                "env = {**os.environ}\n",
                "print('Running train_robust_ensemble.py …')\n",
                "r1 = subprocess.run([sys.executable, str(BASE / 'scripts' / 'train_robust_ensemble.py'),\n",
                "    '--output-dir', out_dir], cwd=str(BASE), env=env)\n",
                "print('Running train_regime_model.py …')\n",
                "r2 = subprocess.run([sys.executable, str(BASE / 'scripts' / 'train_regime_model.py'),\n",
                "    '--output-dir', out_dir], cwd=str(BASE), env=env)\n",
                "print('Done.' if (r1.returncode == 0 and r2.returncode == 0) else 'One or both scripts failed.')",
            ],
        }
            nb["cells"].insert(idx + 1, run_cell)
            print("Inserted 'Run training scripts' cell at index", idx + 1)
            break
    else:
        print("Export section not found; skipping script cell.")

with open(p, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1)
print("Done.")
