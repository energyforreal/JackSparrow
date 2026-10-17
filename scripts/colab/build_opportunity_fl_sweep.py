"""Build the 30m / 24-bar regime-aligned exclusive policy notebook.

Copies the canonical 10m opportunity notebook, freezes resolution, horizon,
and the model family, then appends the regime exclusive sweep cells. The
10m source is not modified.

Run from repo root::

    python scripts/colab/build_opportunity_fl_sweep.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

COLAB_DIR = Path(__file__).resolve().parent
if str(COLAB_DIR) not in sys.path:
    sys.path.insert(0, str(COLAB_DIR))

from patch_opportunity_resolution import patch_notebook  # noqa: E402

SRC_NOTEBOOK = COLAB_DIR / "transformer_btcusd_opportunity_10m.ipynb"
DEST_NOTEBOOK = COLAB_DIR / "transformer_btcusd_opportunity_30m_h24_fl_sweep.ipynb"
SPECS_MODULE = COLAB_DIR / "opportunity_fl_sweep.py"
SWEEP_EXPORT_DIR = "export/opportunity_30m_h24_regime"
SWEEP_ENSEMBLE = '["XGB"]'
BASELINE_SKIP_CELLS: Sequence[str] = ("GATE", "TRAIN", "EVAL", "PROMOTE", "EXPORT")

COLAB_HOWTO = """# BTCUSD 30m regime-aligned exclusive policy (Colab)

Upload **this notebook only**. Do not clone the repo. Runtime: **CPU** (GPU unused).

1. [colab.research.google.com](https://colab.research.google.com) → Upload →
   `transformer_btcusd_opportunity_30m_h24_fl_sweep.ipynb`
2. Runtime → Run all
3. Wait for the last cell (`FL_RUN`). It tags a causal UP/DOWN/RANGE regime,
   trains exclusive long/short labels on (2/2, 3/3, 4/2) ATR books, scores
   non-overlapping R by side and regime, then fits an MLP on the walk-forward
   winner. Download `export/opportunity_30m_h24_regime.zip`
4. Ignore the 10m ensemble wording in the original intro below. Config is
   already frozen to 30m / 24 bars / XGBoost. Baseline TRAIN/EVAL is skipped.
   Direction and return heads are not fit. Live fusion is not written.

From Windows with the Colab CLI already set up:

```powershell
powershell -File scripts/colab/run_colab_cli.ps1 --gpu none `
  --session opportunity-30m-h24-regime --stop-existing --timeout 28800 `
  --notebook scripts/colab/transformer_btcusd_opportunity_30m_h24_fl_sweep.ipynb `
  --bundle-dir opportunity_30m_h24_regime
```
"""

FL_INTRO = """## 17 Regime-aligned exclusive policy (frozen 30m XGBoost)

Features stay frozen: 50 OHLCV columns, 30m bars, 24-bar horizon. Barriers
(2/2, 3/3, 4/2) compete on walk-forward. Labels are exclusive TP-first, kept
only when the causal regime matches the side (UP long, DOWN short, RANGE skip).
Policy uses P(exclusive) plus an adverse-excursion veto; there is no vol floor.
Validation is non-overlapping R, regime baselines, precision curves, and 1.5x
cost stress. MLP (`50 → 64 → 32`) runs only on the walk-forward winner. Test
is scored once only if that winner passes the gate. Live fusion is not written.
"""

FL_RUN_SOURCE = '''# CELL: FL_RUN
from pathlib import Path
import pandas as pd

_sweep_dir = Path(str(CONFIG["export_dir"]))
_sweep_dir.mkdir(parents=True, exist_ok=True)
sweep_payload = run_regime_exclusive_sweep(
    bars,
    config=CONFIG,
    splits=splits,
    wf_folds=wf_folds,
    export_dir=_sweep_dir,
    inner_calibration_split=inner_calibration_split,
)

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)


def _show_stage(name: str, rows: object) -> None:
    print(f"\\n===== {name} =====")
    frame = pd.DataFrame(list(rows or []))
    if frame.empty:
        print("(empty)")
        return
    nested = [
        c
        for c in frame.columns
        if frame[c].map(lambda v: isinstance(v, (dict, list))).any()
    ]
    show = frame.drop(columns=nested) if nested else frame
    print(show.to_string(index=False))


print("n_features", sweep_payload.get("n_features"))
print("policy_heads", sweep_payload.get("policy_heads"))
print("barriers", sweep_payload.get("barriers"))
print("winner_barrier", sweep_payload.get("winner_barrier"))
_show_stage("Barrier compare", sweep_payload.get("barrier_rows"))
_mlp = sweep_payload.get("mlp_policy") or {}
_show_stage("MLP policy folds", _mlp.get("fold_rows"))
_show_stage("Test once", sweep_payload.get("test_rows"))
print("winner_gate", sweep_payload.get("winner_gate"))
print("mlp_test_gate", sweep_payload.get("mlp_test_gate"))
print("ready_to_promote", sweep_payload.get("ready_to_promote"))
print("copied_to_live", sweep_payload.get("copied_to_live"))
import shutil

_zip_path = shutil.make_archive(str(_sweep_dir), "zip", root_dir=str(_sweep_dir))
print("rewrote", _zip_path)
try:
    from google.colab import files

    files.download(str(_sweep_dir) + ".zip")
except ImportError:
    print("Not Colab; files remain under", _sweep_dir)
'''


def _source_lines(text: str) -> List[str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return [ln + "\n" for ln in normalized.splitlines()]


def _code_cell(source: str, cell_id: str) -> Dict[str, Any]:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": _source_lines(source),
        "execution_count": None,
        "outputs": [],
        "id": cell_id,
    }


def _markdown_cell(source: str, cell_id: str) -> Dict[str, Any]:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": _source_lines(source),
        "id": cell_id,
    }


def _cell_text(cell: Dict[str, Any]) -> str:
    source = cell.get("source", [])
    if isinstance(source, str):
        return source
    return "".join(source)


def _patch_config_cell(nb: Dict[str, Any]) -> None:
    patched = False
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        lines = list(source) if isinstance(source, list) else source.splitlines(
            keepends=True
        )
        text = "".join(lines)
        if "# CELL: CONFIG" not in text.splitlines()[0:3]:
            continue
        new_lines: List[str] = []
        for line in lines:
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            nl = "\n" if line.endswith("\n") else ""
            if stripped.startswith('"ensemble":'):
                new_lines.append(f"{indent}\"ensemble\": {SWEEP_ENSEMBLE},{nl}")
            else:
                new_lines.append(line)
            if stripped.startswith("apply_resolution_config(CONFIG)"):
                new_lines.append(f"{indent}CONFIG[\"ensemble\"] = {SWEEP_ENSEMBLE}{nl}")
                new_lines.append(
                    f"{indent}CONFIG[\"export_dir\"] = \"{SWEEP_EXPORT_DIR}\"{nl}"
                )
                new_lines.append(
                    f"{indent}CONFIG[\"run_baseline_train\"] = False{nl}"
                )
        cell["source"] = new_lines
        patched = True
        break
    if not patched:
        raise ValueError("CONFIG cell not found")


def _wrap_baseline_cell(cell: Dict[str, Any], name: str) -> None:
    source = cell.get("source", [])
    lines: List[str]
    if isinstance(source, str):
        lines = source.splitlines(keepends=True)
    else:
        lines = list(source)
    text = "".join(lines)
    if 'if not CONFIG.get("run_baseline_train"' in text:
        return
    marker = f"# CELL: {name}"
    out: List[str] = []
    wrapped = False
    for i, line in enumerate(lines):
        out.append(line)
        if not wrapped and marker in line:
            out.append('if not CONFIG.get("run_baseline_train", True):\n')
            out.append(f'    print("Skipping baseline {name}")\n')
            out.append("else:\n")
            for rest in lines[i + 1 :]:
                if rest.strip() == "":
                    out.append("\n")
                else:
                    prefix = rest if rest.endswith("\n") else rest + "\n"
                    out.append("    " + prefix)
            wrapped = True
            break
    if not wrapped:
        raise ValueError(f"{name} cell not found")
    cell["source"] = out


def _wrap_baseline_cells(nb: Dict[str, Any]) -> None:
    remaining = set(BASELINE_SKIP_CELLS)
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        text = _cell_text(cell)
        for name in list(remaining):
            marker = f"# CELL: {name}"
            head = text.splitlines()[0:3]
            if marker in head or text.startswith(marker):
                _wrap_baseline_cell(cell, name)
                remaining.discard(name)
                break
    if remaining:
        raise ValueError(f"Missing baseline cells to wrap: {sorted(remaining)}")


def build_fl_sweep_notebook(
    src: Path = SRC_NOTEBOOK,
    dest: Path = DEST_NOTEBOOK,
) -> Path:
    """Patch resolution/horizon, freeze XGB, skip baseline, append exclusive sweep."""
    patch_notebook(src, dest, "30m", 24)
    nb: Dict[str, Any] = json.loads(dest.read_text(encoding="utf-8"))
    nb["cells"].insert(0, _markdown_cell(COLAB_HOWTO, "cell-colab-howto"))
    _patch_config_cell(nb)
    _wrap_baseline_cells(nb)
    specs_body = SPECS_MODULE.read_text(encoding="utf-8")
    specs_source = f"# CELL: FL_SPECS\n{specs_body}"
    if not specs_source.endswith("\n"):
        specs_source += "\n"
    nb["cells"].extend(
        [
            _markdown_cell(FL_INTRO, "cell-fl-md"),
            _code_cell(specs_source, "cell-fl-specs"),
            _code_cell(FL_RUN_SOURCE, "cell-fl-run"),
        ]
    )
    dest.write_text(
        json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=SRC_NOTEBOOK)
    parser.add_argument("--dest", type=Path, default=DEST_NOTEBOOK)
    args = parser.parse_args()
    path = build_fl_sweep_notebook(args.src, args.dest)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
