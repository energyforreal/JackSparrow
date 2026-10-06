"""CLI: pick a v15 feature and Label V2 target pair. Does not train a Transformer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.colab.feature_selection import load_train_block, run_feature_label_search


def main(argv: list[str] | None = None) -> int:
    """Load the train-block cache, search pairs, and write selection.json."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--windows-dir",
        type=Path,
        default=Path("export/mtf_fusion_v15/fusion_windows"),
        help="Cached v15 fusion windows (manifest, windows_*.npy, labels_reg.npy).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("export/feature_selection/selection.json"),
        help="Winning feature and label pair.",
    )
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--explain-n", type=int, default=512)
    parser.add_argument("--rank-rows", type=int, default=8000)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    windows_dir = Path(args.windows_dir)
    if not (windows_dir / "manifest.json").is_file():
        raise SystemExit(f"windows cache not found: {windows_dir}")
    print(f"loading train block from {windows_dir}")
    last_bars, path, n_samples, train_end = load_train_block(windows_dir)
    print(
        f"n_samples={n_samples} train_end={train_end} "
        f"last_bars={last_bars.shape} path={path.shape}"
    )
    print(
        "validation and test rows were not loaded. "
        f"trials={int(args.trials)} explain_n={int(args.explain_n)}"
    )
    run_feature_label_search(
        last_bars,
        path,
        n_samples=n_samples,
        train_end=train_end,
        n_trials=int(args.trials),
        output_path=Path(args.output),
        folds=int(args.folds),
        explain_n=int(args.explain_n),
        rank_rows=int(args.rank_rows),
        seed=int(args.seed),
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
