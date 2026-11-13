"""Validate that the recognition notebook runs without this repository."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parent / "recognition_15m_colab.ipynb"

REQUIRED = (
    "def run_colab",
    "def run_optuna_search",
    "optuna.create_study",
    "def spearman_report",
    "def show_recognition_plots",
    "show_recognition_plots(report)",
    "shap.TreeExplainer",
    "files.download",
    "PATTERN_COLUMNS",
    "NATIVE_STRUCTURE_COLS",
)

FORBIDDEN = (
    "git clone",
    "github.com",
    "from research.",
    "import research",
    "from feature_store.",
    "ForecastModelNode",
    "%%writefile",
    "base64.b64decode",
    "import argparse",
)


def _cell_text(cell: dict) -> str:
    """Join a notebook cell's source lines."""
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def _notebook_cells() -> list[dict]:
    """Load the generated notebook cells."""
    if not NOTEBOOK.exists():
        raise AssertionError(f"missing notebook: {NOTEBOOK.name}")
    document = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return list(document["cells"])


def validate_notebook() -> None:
    """Require inlined recognition code and reject a repository clone.

    Raises:
        AssertionError: If the notebook still depends on this repo or an order.
    """
    cells = _notebook_cells()
    text = "\n".join(_cell_text(cell) for cell in cells)
    for token in REQUIRED:
        if token not in text:
            raise AssertionError(f"notebook is missing {token}")
    for token in FORBIDDEN:
        if token in text:
            raise AssertionError(f"notebook mentions {token}")
    if not re.search(r"^report = run_colab\(", text, re.MULTILINE):
        raise AssertionError("notebook does not call run_colab")

    names: dict[str, int] = {}
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = _cell_text(cell)
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[node.name] = names.get(node.name, 0) + 1
    duplicates = sorted(name for name, count in names.items() if count > 1)
    if duplicates:
        raise AssertionError("duplicate notebook definitions: " + ", ".join(duplicates))

    namespace: dict[str, object] = {"__name__": "recognition_notebook"}
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = _cell_text(cell)
        if source.startswith("import importlib.util"):
            continue
        if any(
            token in source
            for token in (
                "drive.mount",
                "files.upload",
                "files.download",
                "api.india.delta.exchange",
            )
        ):
            continue
        if "report = run_colab(" in source:
            if "run_colab" not in namespace:
                raise AssertionError("run_colab is not defined before it is called")
            continue
        if source.strip() == "show_recognition_plots(report)":
            if "show_recognition_plots" not in namespace:
                raise AssertionError(
                    "show_recognition_plots is not defined before it is called"
                )
            continue
        exec(compile(source, NOTEBOOK.name, "exec"), namespace)  # noqa: S102
    if "run_colab" not in namespace or "run_optuna_search" not in namespace:
        raise AssertionError("inlined notebook did not define the recognition entry points")


def main() -> None:
    """Run the notebook structure check."""
    validate_notebook()
    print(f"OK: {NOTEBOOK.name} runs without cloning the repository")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
