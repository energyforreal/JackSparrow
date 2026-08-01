"""Build a self-contained Colab notebook with embedded training modules.

Run from repo root::

    python scripts/colab/build_standalone_notebook.py

Outputs ``transformer_btcusd_all_tf_train_standalone.ipynb`` next to this script.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COLAB_DIR = Path(__file__).resolve().parent
OUTPUT_NOTEBOOK = COLAB_DIR / "transformer_btcusd_all_tf_train_standalone.ipynb"
BUNDLE_ROOT = "/content/colab_bundle"

# Empty stubs avoid importing the full feature_store package tree in Colab.
STUB_INIT_FILES: dict[str, str] = {
    "feature_store/__init__.py": '"""Minimal stub for standalone Colab bundle."""\n',
    "scripts/__init__.py": '"""Minimal stub for standalone Colab bundle."""\n',
    "scripts/colab/__init__.py": '"""Minimal stub for standalone Colab bundle."""\n',
}

SOURCE_FILES: tuple[str, ...] = (
    "feature_store/transformer_btcusd/__init__.py",
    "feature_store/transformer_btcusd/contract.py",
    "feature_store/transformer_btcusd/derivatives.py",
    "feature_store/transformer_btcusd/features.py",
    "feature_store/transformer_btcusd/labels.py",
    "feature_store/transformer_btcusd/inference.py",
    "scripts/colab/transformer_data.py",
    "scripts/colab/transformer_training.py",
    "scripts/colab/train_transformer_resolution.py",
)

INTRO_MARKDOWN = """# BTCUSD Multi-Timeframe Transformer Training (Standalone)

Upload **this notebook only** to Google Colab — no GitHub clone or repo upload required.

Trains independent per-TF transformers for all supported resolutions (5m, 15m, 30m, 1h, 2h).

**Colab setup:** Runtime → Change runtime type → **T4 GPU** (recommended). Run cells top to bottom.

Each TF exports to its own subdirectory under `export_dir`:

```
export/
├── JackSparrow_Transformer_BTCUSD_5m/
│   ├── metadata_transformer.json
│   ├── btcusd_5m_transformer.onnx
│   └── feature_config.json
├── JackSparrow_Transformer_BTCUSD_15m/
└── ...
```

Copy each subdirectory into `agent/model_storage/` after training."""

PIP_CELL = (
    "!pip install -q --upgrade-strategy only-if-needed pyarrow onnx onnxruntime"
)

GPU_CHECK_CELL = """import torch

print(f"PyTorch: {torch.__version__}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
else:
    print("WARNING: No GPU detected — training will run on CPU and be much slower.")
    print("Runtime -> Change runtime type -> select a GPU (T4), then re-run this cell.")
"""

BOOTSTRAP_HEADER = """from pathlib import Path

BUNDLE_ROOT = Path("{bundle_root}")
BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
print(f"Bootstrap target: {{BUNDLE_ROOT}}")
""".format(
    bundle_root=BUNDLE_ROOT
)

PATH_SETUP_CELL = f"""import sys
from pathlib import Path

ROOT = Path("{BUNDLE_ROOT}")
if not (ROOT / "feature_store" / "transformer_btcusd").is_dir():
    raise FileNotFoundError(
        "Bootstrap incomplete: run the bootstrap cells above first."
    )

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
print(f"Using bundle root: {{ROOT}}")
"""

CONFIG_CELL = """from pathlib import Path

from feature_store.transformer_btcusd.contract import SUPPORTED_RESOLUTIONS

resolutions = list(SUPPORTED_RESOLUTIONS)  # or subset: ["15m", "1h"]
export_dir = Path("/content/export")
epochs = None  # e.g. 5 for smoke test
history_days = None
refresh_data = False
continue_on_error = True  # finish remaining TFs if one fails quality gate
"""

TRAIN_CELL = """from scripts.colab.train_transformer_resolution import run_all_training

results = run_all_training(
    resolutions=resolutions,
    export_dir=export_dir,
    epochs=epochs,
    history_days=history_days,
    refresh_data=refresh_data,
    continue_on_error=continue_on_error,
)

for result in results:
    print(result)
"""

SUMMARY_CELL = """import json
from pathlib import Path

print(f"{'Resolution':<12}{'Status':<10}{'Return Corr':<14}Export Dir")
for result in results:
    corr_str = "-"
    if result["status"] == "ok":
        meta_path = Path(result["export_dir"]) / "metadata_transformer.json"
        if meta_path.is_file():
            metrics = json.loads(meta_path.read_text()).get("test_metrics", {})
            corr = metrics.get("future_return", {}).get("corr")
            if corr is not None:
                corr_str = f"{corr:+.4f}"
    print(f"{result['resolution']:<12}{result['status']:<10}{corr_str:<14}{result['export_dir']}")
"""

ZIP_CELL = """import shutil
from pathlib import Path

zip_path = shutil.make_archive("/content/transformer_exports", "zip", export_dir)
print(f"Download: {zip_path}")

try:
    from google.colab import files
    files.download(zip_path)
except ImportError:
    print("Not running in Colab; download manually from the path above.")
"""


def _code_cell(source: str) -> dict[str, Any]:
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return {"cell_type": "code", "metadata": {}, "source": lines, "outputs": [], "execution_count": None}


def _markdown_cell(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": [source]}


def _writefile_cell(relative_path: str, content: str) -> dict[str, Any]:
    target = f"{BUNDLE_ROOT}/{relative_path}"
    body = content.rstrip("\n") + "\n"
    source = f"%%writefile {target}\n{body}"
    return _code_cell(source)


def _read_source(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Missing source file: {path}")
    return path.read_text(encoding="utf-8")


def build_notebook() -> dict[str, Any]:
    cells: list[dict[str, Any]] = [
        _markdown_cell(INTRO_MARKDOWN),
        _code_cell(PIP_CELL),
        _code_cell(GPU_CHECK_CELL),
        _markdown_cell("## Bootstrap training modules"),
        _code_cell(BOOTSTRAP_HEADER),
    ]

    for relative_path, content in STUB_INIT_FILES.items():
        cells.append(_writefile_cell(relative_path, content))

    for relative_path in SOURCE_FILES:
        cells.append(_writefile_cell(relative_path, _read_source(relative_path)))

    cells.extend(
        [
            _markdown_cell("## Configure and train"),
            _code_cell(PATH_SETUP_CELL),
            _code_cell(CONFIG_CELL),
            _code_cell(TRAIN_CELL),
            _markdown_cell("## Results summary"),
            _code_cell(SUMMARY_CELL),
            _code_cell(ZIP_CELL),
        ]
    )

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
            "colab": {"provenance": []},
        },
        "cells": cells,
    }


def validate_notebook(notebook: dict[str, Any]) -> None:
    """Ensure generated notebook has expected bootstrap layout."""
    cells = notebook.get("cells", [])
    writefile_sources = [
        "".join(cell.get("source", []))
        for cell in cells
        if cell.get("cell_type") == "code"
        and "".join(cell.get("source", [])).startswith("%%writefile")
    ]
    n_modules = len(STUB_INIT_FILES) + len(SOURCE_FILES)
    if len(cells) < 20:
        raise RuntimeError(f"Expected >= 20 cells, got {len(cells)}")
    if len(writefile_sources) != n_modules:
        raise RuntimeError(
            f"Expected {n_modules} writefile cells, got {len(writefile_sources)}"
        )

    required_paths = {f"{BUNDLE_ROOT}/{rel}" for rel in STUB_INIT_FILES} | {
        f"{BUNDLE_ROOT}/{rel}" for rel in SOURCE_FILES
    }
    written_paths = {line.split()[1] for line in writefile_sources}
    missing = required_paths - written_paths
    if missing:
        raise RuntimeError(f"Notebook missing writefile targets: {sorted(missing)}")


def main() -> None:
    notebook = build_notebook()
    validate_notebook(notebook)
    OUTPUT_NOTEBOOK.write_text(
        json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    n_cells = len(notebook["cells"])
    n_modules = len(STUB_INIT_FILES) + len(SOURCE_FILES)
    print(f"Wrote {OUTPUT_NOTEBOOK}")
    print(f"  cells: {n_cells} ({n_modules} bootstrap writefile cells)")


if __name__ == "__main__":
    main()
