"""Generate a standalone Colab notebook for 15-minute recognition.

The notebook contains the training code and fetches public BTCUSD 5-minute
candles from Delta Exchange. It does not clone this repository.

Run from the repo root::

    python scripts/colab/build_recognition_15m_notebook.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.colab.build_standalone_notebook import (  # noqa: E402
    _code_cell,
    _markdown_cell,
    _strip_cli_entrypoint,
)

OUTPUT = Path(__file__).resolve().parent / "recognition_15m_colab.ipynb"

INLINE_MODULE_ORDER: tuple[tuple[str, str], ...] = (
    ("## Contract", "research/recognition_15m/contract.py"),
    ("## Completed 15-minute bars", "research/recognition_15m/bars.py"),
    ("## Causal features", "research/recognition_15m/features.py"),
    ("## Geometric labels", "research/recognition_15m/labels.py"),
    ("## Purged splits", "research/recognition_15m/splits.py"),
    ("## Leakage checks", "research/recognition_15m/integrity.py"),
    ("## Windows", "research/recognition_15m/dataset.py"),
    ("## Causal TCN", "research/recognition_15m/models.py"),
    ("## Optuna search", "research/recognition_15m/search.py"),
    ("## Correlation and TreeSHAP", "research/recognition_15m/explain.py"),
    ("## Figures", "research/recognition_15m/plots.py"),
    ("## Colab entry point", "research/recognition_15m/colab.py"),
)

_INTRO = """# 15-minute recognition training

Upload **this notebook** to Google Colab and run the cells from top to bottom.
The training code is in the notebook. A GitHub clone is not required.

The data cell loads BTCUSD 5-minute candles from the public Delta Exchange
history API and writes `/content/btcusd_5m_raw.parquet`. It does not connect
to Google Drive and it does not ask for a file upload.

Use a GPU runtime. The fit predicts geometric candle families and market state
from 48 completed 15-minute bars. Each bar also carries causal support and
resistance distance, proximity, touch counts, and range position. After the
fit, the next cells draw the
learning curve, validation against the sealed test, the Optuna trial scores,
the label correlation heatmaps, and the SHAP ranking. Leave the checkpoint
in the Colab output folder. It is a research artifact.
"""

_INSTALL = """import importlib.util
import subprocess
import sys

def _pip(*packages: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *packages])

if importlib.util.find_spec("torch") is None:
    _pip("torch")
_pip(
    "optuna", "shap", "xgboost", "scipy", "pandas", "pyarrow",
    "matplotlib", "structlog",
)
print("recognition dependencies ready")
"""

_DATA = """import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

# Public history. No API key. One response holds about 4,000 candles.
DELTA_CANDLES_URL = "https://api.india.delta.exchange/v2/history/candles"
PAGE_BARS = 4_000
BAR_SECONDS = 300
TARGET_BARS = 100_000
MIN_BARS = 15_000
LOOKBACK_DAYS = 730
PAUSE_SECONDS = 0.35


def _candle_page(start: int, end: int) -> list[dict]:
    \"\"\"Request one public BTCUSD 5-minute page.\"\"\"
    query = urllib.parse.urlencode(
        {
            "symbol": "BTCUSD",
            "resolution": "5m",
            "start": int(start),
            "end": int(end),
        }
    )
    request = urllib.request.Request(
        f"{DELTA_CANDLES_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "JackSparrow-recognition/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("success") is False:
        raise RuntimeError("Delta candle history returned success=false")
    result = payload.get("result", [])
    if isinstance(result, dict):
        result = result.get("candles", [])
    if not isinstance(result, list):
        raise RuntimeError("Delta candle history did not return a list")
    return result


def fetch_btcusd_5m(target: int = TARGET_BARS) -> pd.DataFrame:
    \"\"\"Walk backward through public 5-minute candles and return OHLCV.\"\"\"
    end = int(time.time())
    earliest = end - LOOKBACK_DAYS * 24 * 60 * 60
    rows: list[dict] = []
    seen: set[int] = set()
    while len(rows) < target and end > earliest:
        start = max(earliest, end - PAGE_BARS * BAR_SECONDS)
        page = _candle_page(start, end)
        if not page:
            break
        oldest = end
        added = 0
        for row in page:
            stamp = int(row["time"])
            oldest = min(oldest, stamp)
            if stamp in seen:
                continue
            seen.add(stamp)
            rows.append(row)
            added += 1
        nxt = oldest - 1
        if nxt >= end or added == 0:
            break
        end = nxt
        print(f"delta 5m candles: {len(rows)}", flush=True)
        if len(rows) >= target:
            break
        time.sleep(PAUSE_SECONDS)
    if len(rows) < MIN_BARS:
        raise RuntimeError(
            f"Delta returned {len(rows)} five-minute candles; "
            f"need at least {MIN_BARS}."
        )
    frame = pd.DataFrame(rows)
    frame["time"] = pd.to_datetime(frame["time"].astype("int64"), unit="s", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["time", "open", "high", "low", "close", "volume"])
    frame = frame.sort_values("time").drop_duplicates("time", keep="last")
    frame = frame.tail(target).reset_index(drop=True)
    return frame.loc[:, ["time", "open", "high", "low", "close", "volume"]]


parquet = Path("/content/btcusd_5m_raw.parquet")
candles = fetch_btcusd_5m()
candles.to_parquet(parquet, index=False)
print(
    parquet,
    len(candles),
    candles["time"].iloc[0],
    candles["time"].iloc[-1],
)
"""

_TRAIN = """from pathlib import Path

report = run_colab(
    source=parquet,
    output_dir=Path("/content/export/recognition_15m/colab"),
)
print(report["test"]["geometry_macro_f1"])
print(report["test"]["geometry_calibration"]["expected_calibration_error"])
print(report["zip_path"])
"""

_READ = """## How to read the figures

The next cell draws the figures from the report already in memory. It does
not train again.

- **Learning curve.** Train loss and validation loss for the final TCN. The
  dashed line is the epoch whose weights are saved. A train line that keeps
  falling while validation turns up means later epochs fit the training
  windows more tightly than the validation windows.
- **Validation against the sealed test.** Macro-F1 for geometry, market
  state, and the structure tag, then F1 for each geometric family. The test
  bars are the one sealed score.
- **Development search.** Each dot is one Optuna trial. The line is the best
  completed trial so far. Pruned trials were stopped early on a validation fold.
- **Correlation.** Spearman on training windows only. The left heatmap uses
  the last bar of each window. The right heatmap uses the window mean. A black
  box marks a pair whose absolute correlation is at least 0.5. A high value
  on `body_to_range` versus `doji` is the candle rule showing through an
  allowed channel.
- **TreeSHAP.** Mean absolute contribution of each channel to the presence
  baseline, summed across the 48 bars. Taller bars are the channels the trees
  used. This ranking does not change the TCN.
- **Reliability.** For Head A on the sealed test, each point is a probability
  bin. A point on the dashed line means the predicted probability matches how
  often the family was present. Larger points are bins with more rows.
"""

_SHOW = """show_recognition_plots(report)
"""

_DOWNLOAD = """try:
    from google.colab import files
    files.download(report["zip_path"])
except Exception as exc:
    print("browser download skipped:", exc)
    print(report["zip_path"])
"""


def _is_internal_module(module: str | None) -> bool:
    """True for packages that the notebook defines in earlier cells."""
    if not module:
        return False
    root = module.split(".", maxsplit=1)[0]
    return root in {"research", "feature_store", "scripts"}


def _strip_internal_imports(source: str) -> str:
    """Drop imports that the preceding notebook cells already define."""
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    drop_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and _is_internal_module(node.module):
            end = node.end_lineno or node.lineno
            drop_lines.update(range(node.lineno, end + 1))
        elif isinstance(node, ast.Import):
            internal = any(
                _is_internal_module(alias.name) for alias in node.names
            )
            if internal:
                end = node.end_lineno or node.lineno
                drop_lines.update(range(node.lineno, end + 1))
    kept = [line for index, line in enumerate(lines, start=1) if index not in drop_lines]
    text = "".join(kept).strip()
    return text + "\n"


def _prepare_module(relative_path: str) -> str:
    """Read one recognition module and make it safe to paste into a cell."""
    path = REPO_ROOT / relative_path
    source = path.read_text(encoding="utf-8")
    prepared = _strip_cli_entrypoint(_strip_internal_imports(source))
    if "from research." in prepared or "import research" in prepared:
        raise RuntimeError(f"internal import remains in {relative_path}")
    if "from feature_store." in prepared:
        raise RuntimeError(f"feature-store import remains in {relative_path}")
    ast.parse(prepared)
    return prepared


def _tuple_literal(name: str, values: tuple[str, ...]) -> str:
    """One name per line so the denylist stays readable in the notebook."""
    body = ",\n".join(f"    {item!r}" for item in values)
    return f"{name} = (\n{body},\n)\n"


def _denylist_source() -> str:
    """Snapshot the refused column names from the live contracts."""
    from feature_store.transformer_btcusd.contract import NATIVE_STRUCTURE_COLS
    from research.forecast_30m.contract_v4 import PATTERN_COLUMNS

    note = (
        "# Refused column names, copied when this notebook is generated.\n"
        "# The cell does not import the rest of the repository.\n"
    )
    return note + _tuple_literal(
        "PATTERN_COLUMNS", tuple(PATTERN_COLUMNS)
    ) + _tuple_literal(
        "NATIVE_STRUCTURE_COLS", tuple(NATIVE_STRUCTURE_COLS)
    )


def build_notebook() -> dict[str, Any]:
    """Assemble the standalone recognition notebook.

    Returns:
        An nbformat document.
    """
    cells: list[dict[str, Any]] = [
        _markdown_cell(_INTRO),
        _markdown_cell("## Setup"),
        _code_cell(_INSTALL),
        _markdown_cell("## Refused column names"),
        _code_cell(_denylist_source()),
    ]
    for heading, relative_path in INLINE_MODULE_ORDER:
        cells.append(_markdown_cell(heading))
        cells.append(_code_cell(_prepare_module(relative_path)))
    cells.extend(
        [
            _markdown_cell("## Fetch the 5-minute candles"),
            _code_cell(_DATA),
            _markdown_cell("## Search, explain, and score the sealed test"),
            _code_cell(_TRAIN),
            _markdown_cell(_READ),
            _code_cell(_SHOW),
            _markdown_cell("## Download the research zip"),
            _code_cell(_DOWNLOAD),
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
            "accelerator": "GPU",
            "colab": {"provenance": []},
        },
        "cells": cells,
    }


def main() -> None:
    """Write the notebook next to this script."""
    document = build_notebook()
    OUTPUT.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
