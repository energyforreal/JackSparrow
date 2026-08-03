"""Build a self-contained Colab notebook with inline training code cells.

Run from repo root::

    python scripts/colab/build_standalone_notebook.py

Outputs ``transformer_btcusd_all_tf_train_standalone.ipynb`` next to this script.
All training logic is emitted as readable Python cells (no base64, no %%writefile).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COLAB_DIR = Path(__file__).resolve().parent
OUTPUT_NOTEBOOK = COLAB_DIR / "transformer_btcusd_all_tf_train_standalone.ipynb"

NOTEBOOK_CELL_SPLIT = "# --- NOTEBOOK_CELL_SPLIT ---"
MAX_LINE_LENGTH = 500

INLINE_MODULE_ORDER: tuple[tuple[str, str], ...] = (
    ("## Feature contract (agent integration)", "feature_store/transformer_btcusd/contract.py"),
    ("## Derivatives features", "feature_store/transformer_btcusd/derivatives.py"),
    ("## Feature engineering", "feature_store/transformer_btcusd/features.py"),
    ("## Labels / targets", "feature_store/transformer_btcusd/labels.py"),
    ("## Inference and export helpers", "feature_store/transformer_btcusd/inference.py"),
    ("## Delta Exchange India data", "scripts/colab/transformer_data.py"),
    ("## Training pipeline", "scripts/colab/transformer_training.py"),
    ("## Training runner", "scripts/colab/train_transformer_resolution.py"),
)

REQUIRED_SYMBOLS: tuple[str, ...] = (
    "FEATURE_COLS",
    "fetch_candles",
    "MarketTransformer",
    "run_all_training",
)

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "_PAYLOAD_B64",
    "base64.b64decode",
    "%%writefile",
    "colab_bundle",
)

INTRO_MARKDOWN = """# BTCUSD Multi-Timeframe Transformer Training (Standalone)

Delta Exchange India data → feature engineering → market-understanding labels → Transformer → ONNX export.

Upload **this notebook only** to Google Colab — no GitHub clone, no file uploads. Historical
OHLCV, funding, and OI are pulled from the **Delta Exchange India public API** at runtime.

**Run all cells top-to-bottom.** Training code is inline in this notebook (readable Python cells).

### Cell map (troubleshooting)

| Section | What to inspect |
|---------|-----------------|
| Feature contract | `FEATURE_COLS`, `CONTINUOUS_LABEL_COLS`, horizons |
| Derivatives | Funding/OI z-scores |
| Feature engineering | `add_features` |
| Labels / targets | `compute_market_labels` |
| Inference helpers | `feature_config.json` builders |
| Delta data | `fetch_candles`, `fetch_history_bundle` |
| Training pipeline | `MarketTransformer`, train loop, ONNX export |
| Training runner | `run_training`, `run_all_training` |
| Configure & train | `resolutions`, `epochs`, `history_days` |

Permanent edits: change repo `.py` files under `feature_store/transformer_btcusd/` and
`scripts/colab/`, then regenerate::

    python scripts/colab/build_standalone_notebook.py

**Colab setup:** Runtime → Change runtime type → **T4 GPU** (recommended).

Each TF exports to its own subdirectory under `export_dir`:

```
export/
├── JackSparrow_Transformer_BTCUSD_5m/
│   ├── metadata_transformer.json
│   ├── btcusd_5m_transformer.onnx
│   └── feature_config.json
└── ...
```

Copy each subdirectory into `agent/model_storage/` after training."""

NOTES_MARKDOWN = """## Notes before wiring into your live agent

- **No trading label was trained** — models predict continuous market properties + a volatility-regime
  class. Trading decisions are a downstream step in JackSparrow.
- **Label horizon** scales to ~8 hours wall-clock per TF (32 bars on 15m, 96 on 5m, etc.). It is
  independent of `window_len` (input lookback) and worth sweeping separately.
- **Early stopping is enabled** by default (patience 12, max 120 epochs); best val-loss checkpoint is
  used for export.
- **Feature parity is the #1 deployment failure mode** — train/serve uses
  `feature_store/transformer_btcusd/` (not `unified_feature_engine`). Run
  `pytest tests/unit/test_transformer_btcusd_feature_parity.py` before deploy.
- **Export quality tiers** — sanity floors block broken exports; promotion targets in metadata are
  informational, not proof of tradability.
- **ONNX export** embeds all weights in a single file (`dynamo=False`) and is verified before download."""

PIP_CELL = (
    "# Colab ships torch/pandas/numpy; only install what training needs beyond that.\n"
    "!pip install -q --upgrade-strategy only-if-needed "
    "pyarrow onnx onnxruntime requests"
)

GPU_CHECK_CELL = """import torch

print(f"PyTorch: {torch.__version__}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
else:
    print("WARNING: No GPU detected — training will run on CPU and be much slower.")
    print("Runtime -> Change runtime type -> select a GPU (T4), then re-run this cell.")
"""

CONFIG_PREVIEW_CELL = """import json

print("Per-TF label horizons (~8h wall-clock):")
for res in SUPPORTED_RESOLUTIONS:
    bars = label_horizon_bars_for_resolution(RESOLUTION_MINUTES[res])
    print(f"  {res:>4s}: {bars:3d} bars")

print("\\n15m default_training_config:")
print(json.dumps(default_training_config("15m"), indent=2))
"""

CONFIG_CELL = """from pathlib import Path

# Train all TFs or a subset, e.g. ["15m"] for a quick smoke test.
resolutions = list(SUPPORTED_RESOLUTIONS)
export_dir = Path("/content/export")
export_dir.mkdir(parents=True, exist_ok=True)
cache_dir = Path("/content/cache")
cache_dir.mkdir(parents=True, exist_ok=True)

# Optional overrides (None = use per-TF defaults from default_training_config).
epochs = None  # e.g. 5 for smoke test
history_days = None  # e.g. 900; BTCUSD India history ~950 days as of 2026
refresh_data = False  # set True to re-fetch from Delta API instead of parquet cache
continue_on_error = True  # finish remaining TFs if one fails quality gate
enforce_quality_gate = True  # set False to export even if future_return corr is low
"""

TRAIN_CELL = """results = run_all_training(
    resolutions=resolutions,
    export_dir=export_dir,
    cache_dir=cache_dir,
    epochs=epochs,
    history_days=history_days,
    refresh_data=refresh_data,
    continue_on_error=continue_on_error,
    enforce_quality_gate=enforce_quality_gate,
)

for result in results:
    print(result)
"""

SUMMARY_CELL = """import json
from pathlib import Path

if "results" not in globals():
    raise NameError("Run the training cell above first.")

print(f"{'Resolution':<10}{'Status':<8}{'Return Corr':<14}Export Dir")
for result in results:
    corr_str = "-"
    if result["status"] == "ok":
        meta_path = Path(result["export_dir"]) / "metadata_transformer.json"
        if meta_path.is_file():
            metrics = json.loads(meta_path.read_text()).get("test_metrics", {})
            corr = metrics.get("future_return", {}).get("corr")
            if corr is not None:
                corr_str = f"{corr:+.4f}"
    print(
        f"{result['resolution']:<10}{result['status']:<8}{corr_str:<14}{result['export_dir']}"
    )
    if result["status"] != "ok" and result.get("error"):
        print(f"  error: {result['error']}")
"""

ZIP_CELL = """import shutil
from pathlib import Path

if "export_dir" not in globals():
    raise NameError("Run the config cell above first.")

if not export_dir.is_dir():
    raise FileNotFoundError(f"Export dir not found: {export_dir}. Run training first.")

bundles = [p for p in export_dir.iterdir() if p.is_dir()]
if not bundles:
    print("No TF bundles exported. Check training results above.")
else:
    zip_path = shutil.make_archive("/content/transformer_exports", "zip", export_dir)
    print(f"Download: {zip_path} ({len(bundles)} bundle(s))")

    try:
        from google.colab import files
        files.download(zip_path)
    except ImportError:
        print("Not running in Colab; download manually from the path above.")
"""


def _is_internal_module(module: str | None) -> bool:
    if not module:
        return False
    return module == "feature_store" or module.startswith("feature_store.") or module.startswith(
        "scripts"
    )


def _strip_internal_imports(source: str) -> str:
    """Remove imports from feature_store.* and scripts.* (defined in prior notebook cells)."""
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    drop_lines: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if _is_internal_module(node.module):
                end = node.end_lineno or node.lineno
                drop_lines.update(range(node.lineno, end + 1))
        elif isinstance(node, ast.Import):
            if any(
                alias.name.split(".")[0] in ("feature_store", "scripts") for alias in node.names
            ):
                end = node.end_lineno or node.lineno
                drop_lines.update(range(node.lineno, end + 1))

    kept = [line for idx, line in enumerate(lines, start=1) if idx not in drop_lines]
    text = "".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _read_source(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Missing source file: {path}")
    return path.read_text(encoding="utf-8")


def _prepare_module_chunks(relative_path: str) -> list[str]:
    raw = _read_source(relative_path)
    prepared = _strip_internal_imports(raw)
    if NOTEBOOK_CELL_SPLIT in prepared:
        return [chunk.strip() + "\n" for chunk in prepared.split(NOTEBOOK_CELL_SPLIT) if chunk.strip()]
    return [prepared]


def _code_cell(source: str) -> dict[str, Any]:
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return {
        "cell_type": "code",
        "metadata": {},
        "source": lines,
        "outputs": [],
        "execution_count": None,
    }


def _markdown_cell(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": [source]}


def _inline_module_cells() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for heading, relative_path in INLINE_MODULE_ORDER:
        cells.append(_markdown_cell(heading))
        for chunk in _prepare_module_chunks(relative_path):
            cells.append(_code_cell(chunk))
    return cells


def build_notebook() -> dict[str, Any]:
    cells: list[dict[str, Any]] = [
        _markdown_cell(INTRO_MARKDOWN),
        _markdown_cell("## Setup"),
        _code_cell(PIP_CELL),
        _code_cell(GPU_CHECK_CELL),
        *_inline_module_cells(),
        _markdown_cell("## Configure and train"),
        _code_cell(CONFIG_PREVIEW_CELL),
        _code_cell(CONFIG_CELL),
        _markdown_cell("## Train all resolutions"),
        _code_cell(TRAIN_CELL),
        _markdown_cell("## Results summary"),
        _code_cell(SUMMARY_CELL),
        _markdown_cell("## Download exports"),
        _code_cell(ZIP_CELL),
        _markdown_cell(NOTES_MARKDOWN),
    ]

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


def _cell_text(cell: dict[str, Any]) -> str:
    return "".join(cell.get("source", []))


def validate_notebook(notebook: dict[str, Any]) -> None:
    """Ensure generated notebook has expected inline layout."""
    cells = notebook.get("cells", [])
    if len(cells) < 18:
        raise RuntimeError(f"Expected >= 18 cells, got {len(cells)}")

    full_text = "\n".join(_cell_text(c) for c in cells)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in full_text:
            raise RuntimeError(f"Forbidden pattern in notebook: {pattern!r}")

    for symbol in REQUIRED_SYMBOLS:
        if symbol not in full_text:
            raise RuntimeError(f"Missing required symbol: {symbol!r}")

    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        for line in _cell_text(cell).splitlines():
            if len(line) > MAX_LINE_LENGTH:
                raise RuntimeError(
                    f"Line exceeds {MAX_LINE_LENGTH} chars (possible blob regression): "
                    f"{line[:80]}..."
                )

    writefile_cells = [
        c for c in cells if c.get("cell_type") == "code" and _cell_text(c).startswith("%%writefile")
    ]
    if writefile_cells:
        raise RuntimeError(f"Found {len(writefile_cells)} %%writefile cells")

    internal_import_re = re.compile(r"^\s*from (feature_store|scripts)\.")
    for cell in cells:
        text = _cell_text(cell)
        if "run_all_training(" in text and "def run_all_training" not in text:
            for line in text.splitlines():
                if internal_import_re.match(line):
                    raise RuntimeError(
                        f"Train/config cell must not import internal packages: {line.strip()}"
                    )

    train_idx = next(
        i for i, c in enumerate(cells) if "run_all_training(" in _cell_text(c) and "def " not in _cell_text(c)
    )
    contract_idx = next(i for i, c in enumerate(cells) if "FEATURE_COLS" in _cell_text(c))
    if contract_idx >= train_idx:
        raise RuntimeError("FEATURE_COLS cell must appear before train cell")


def main() -> None:
    notebook = build_notebook()
    validate_notebook(notebook)
    OUTPUT_NOTEBOOK.write_text(
        json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    n_cells = len(notebook["cells"])
    n_modules = len(INLINE_MODULE_ORDER)
    print(f"Wrote {OUTPUT_NOTEBOOK}")
    print(f"  cells: {n_cells} ({n_modules} inline module sections)")


if __name__ == "__main__":
    main()
