"""Generate the eight swinging Colab notebooks.

Each notebook writes the research package onto ``/content/JackSparrow`` and
keeps datasets under ``/content/JackSparrow/data``. Nothing mounts Google Drive.

Run from the repo root::

    python scripts/colab/build_swinging_notebooks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.colab.build_standalone_notebook import _code_cell, _markdown_cell  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent

_MATERIALIZE = (
    "research/__init__.py",
    "research/cpr_mtf/__init__.py",
    "research/cpr_mtf/contract.py",
    "research/cpr_mtf/swings.py",
    "research/cpr_mtf/features.py",
    "research/cpr_mtf/bars.py",
    "research/cpr_mtf/candidates.py",
    "feature_store/__init__.py",
    "feature_store/feature_registry.py",
    "feature_store/feature_pipeline.py",
    "feature_store/feature_cache.py",
    "feature_store/drift.py",
    "feature_store/perpetual_features.py",
    "feature_store/unified_feature_engine.py",
    "feature_store/pattern_features/__init__.py",
    "feature_store/pattern_features/pattern_utils.py",
    "feature_store/pattern_features/candlestick_patterns.py",
    "feature_store/pattern_features/chart_patterns.py",
    "feature_store/transformer_btcusd/__init__.py",
    "feature_store/transformer_btcusd/contract.py",
    "feature_store/transformer_btcusd/derivatives.py",
    "feature_store/transformer_btcusd/structure.py",
    "feature_store/transformer_btcusd/features.py",
    "feature_store/transformer_btcusd/inference.py",
    "scripts/colab/transformer_data.py",
    "research/swinging/__init__.py",
    "research/swinging/contract.py",
    "research/swinging/quality.py",
    "research/swinging/data.py",
    "research/swinging/regime.py",
    "research/swinging/features.py",
    "research/swinging/setups.py",
    "research/swinging/outcomes.py",
    "research/swinging/splits.py",
    "research/swinging/fusion.py",
    "research/swinging/models.py",
    "research/swinging/evaluate.py",
    "research/swinging/export_bundle.py",
)

_INSTALL = """import subprocess
import sys

subprocess.check_call([
    sys.executable, "-m", "pip", "install", "-q",
    "pandas", "pyarrow", "numpy", "scipy", "scikit-learn",
    "xgboost", "lightgbm", "optuna", "joblib", "requests",
])
print("swinging dependencies ready")
"""

_INTRO = """# Swinging research notebook {notebook_id}

Run the cells from top to bottom on Google Colab. The notebook writes its
Python package to `/content/JackSparrow` and its datasets to
`/content/JackSparrow/data`.

Data is downloaded from the public Delta Exchange candle API. Do not mount
Google Drive. After a runtime reset, run this notebook again. It rebuilds the
package from the cells and can rebuild the parquet inputs from Delta or from
parquet already stored under `/content/JackSparrow/data`.

These artifacts are research only. They do not enable live orders.
"""

_NOTEBOOKS = (
    (
        "01_delta_historical_data.ipynb",
        "01",
        """from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.data import collect_all

reports = collect_all(COLAB_DATA_ROOT)
print(COLAB_DATA_ROOT)
for resolution, report in reports.items():
    manifest = report["manifests"]["ohlcv"]
    print(resolution, manifest["rows"], manifest["earliest"], manifest["latest"])
""",
    ),
    (
        "02_feature_engineering.ipynb",
        "02",
        """from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.features import materialize_features

written = materialize_features(COLAB_DATA_ROOT)
print(written)
""",
    ),
    (
        "03_algorithmic_setup_generation.ipynb",
        "03",
        """from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.setups import materialize_setups

written = materialize_setups(COLAB_DATA_ROOT)
print(written)
""",
    ),
    (
        "04_trade_outcome_engine.ipynb",
        "04",
        """from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.outcomes import materialize_outcomes

written = materialize_outcomes(COLAB_DATA_ROOT)
print(written)
""",
    ),
    (
        "05_setup_effectiveness_training.ipynb",
        "05",
        """from pathlib import Path

from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.models import train_setup_effectiveness

storage_dir = Path(COLAB_DATA_ROOT) / "optuna"
storage_dir.mkdir(parents=True, exist_ok=True)
artifact = train_setup_effectiveness(
    COLAB_DATA_ROOT,
    n_trials=8,
    storage="sqlite:///" + str(storage_dir / "setup.db"),
)
print(artifact["classifier_algorithm"], artifact["sealed_start"])
""",
    ),
    (
        "06_sr_effectiveness_training.ipynb",
        "06",
        """from pathlib import Path

from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.models import train_regime_model, train_sr_effectiveness

storage_dir = Path(COLAB_DATA_ROOT) / "optuna"
storage_dir.mkdir(parents=True, exist_ok=True)
sr_artifact = train_sr_effectiveness(
    COLAB_DATA_ROOT,
    n_trials=8,
    storage="sqlite:///" + str(storage_dir / "sr.db"),
)
regime_artifact = train_regime_model(
    COLAB_DATA_ROOT,
    n_trials=4,
    storage="sqlite:///" + str(storage_dir / "regime.db"),
)
print(sr_artifact["task"], regime_artifact["task"])
""",
    ),
    (
        "07_walk_forward_backtesting.ipynb",
        "07",
        """from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.evaluate import materialize_comparison

report = materialize_comparison(COLAB_DATA_ROOT)
for strategy, metrics in report.items():
    print(strategy, metrics["trades"], metrics["net_expectancy"])
""",
    ),
    (
        "08_model_export.ipynb",
        "08",
        """from research.swinging.contract import COLAB_DATA_ROOT
from research.swinging.export_bundle import export_download_zip

setup_zip = export_download_zip(COLAB_DATA_ROOT, task="setup_effectiveness")
sr_zip = export_download_zip(COLAB_DATA_ROOT, task="sr_effectiveness")
print(setup_zip)
print(sr_zip)
""",
    ),
)


def _materialize_source() -> str:
    payload = {}
    for relative in _MATERIALIZE:
        path = REPO_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing notebook source: {path}")
        payload[relative] = path.read_text(encoding="utf-8")
    encoded = json.dumps(json.dumps(payload))
    return (
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "ROOT = Path('/content/JackSparrow')\n"
        f"FILES = json.loads({encoded})\n"
        "for relative, text in FILES.items():\n"
        "    destination = ROOT / relative\n"
        "    destination.parent.mkdir(parents=True, exist_ok=True)\n"
        "    destination.write_text(text, encoding='utf-8')\n"
        "sys.path.insert(0, str(ROOT))\n"
        "print('materialized', len(FILES), 'files under', ROOT)\n"
    )


def build_notebook(filename: str, notebook_id: str, driver: str) -> dict:
    """Return one notebook document.

    Args:
        filename: Output file name.
        notebook_id: Short id shown in the title.
        driver: Final code cell.

    Returns:
        Notebook JSON structure.
    """
    intro = _INTRO.format(notebook_id=notebook_id)
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        },
        "cells": [
            _markdown_cell(intro),
            _markdown_cell("## Install"),
            _code_cell(_INSTALL),
            _markdown_cell("## Local package"),
            _code_cell(_materialize_source()),
            _markdown_cell("## Run"),
            _code_cell(driver),
        ],
    }


def main() -> None:
    """Write all eight notebooks."""
    for filename, notebook_id, driver in _NOTEBOOKS:
        document = build_notebook(filename, notebook_id, driver)
        destination = OUTPUT_DIR / filename
        destination.write_text(json.dumps(document), encoding="utf-8")
        print(destination)


if __name__ == "__main__":
    main()
