#!/usr/bin/env python3
"""
Sanity-check v15 pipeline joblibs under MODEL_DIR (or a given root).

Expects layout:
  <root>/5m/metadata_BTCUSD_5m.json + pipeline_5m_v14.pkl
  <root>/15m/metadata_BTCUSD_15m.json + pipeline_15m_v14.pkl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_meta(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _check_pipeline(meta_path: Path, pkl_name: str) -> None:
    pkl = meta_path.parent / pkl_name
    if not pkl.is_file():
        raise FileNotFoundError(f"Missing pipeline: {pkl}")
    import joblib

    loaded = joblib.load(pkl)
    pipe = loaded["model"] if isinstance(loaded, dict) and "model" in loaded else loaded
    meta = _load_meta(meta_path)
    feats = meta.get("features") or meta.get("features_required")
    if not feats:
        raise ValueError(f"No features list in {meta_path}")
    import numpy as np

    med = (meta.get("train_median") or {})
    row = []
    for name in feats:
        v = med.get(name, 0.0)
        try:
            row.append(float(v))
        except (TypeError, ValueError):
            row.append(0.0)
    X = np.array([row], dtype=np.float64)
    if not hasattr(pipe, "predict_proba"):
        raise TypeError(f"{pkl} has no predict_proba")
    proba = pipe.predict_proba(X)
    if proba.shape != (1, 3):
        raise ValueError(f"{pkl} predict_proba shape {proba.shape}, expected (1, 3)")
    classes = getattr(pipe, "classes_", None)
    if classes is not None and list(classes) != [0, 1, 2]:
        print("warning: unexpected classes_:", list(classes), file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate v15 pipeline pickles.")
    ap.add_argument(
        "root",
        nargs="?",
        default=os.environ.get(
            "MODEL_DIR",
            str(Path(__file__).resolve().parents[1] / "agent/model_storage/jacksparrow_v15_BTCUSD_2026-04-05"),
        ),
        help="Bundle root containing 5m/ and 15m/ subfolders",
    )
    args = ap.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1
    pairs = [
        (root / "5m" / "metadata_BTCUSD_5m.json", "pipeline_5m_v14.pkl"),
        (root / "15m" / "metadata_BTCUSD_15m.json", "pipeline_15m_v14.pkl"),
    ]
    for meta_path, pkl in pairs:
        if not meta_path.is_file():
            print(f"skip (no metadata): {meta_path}")
            continue
        try:
            _check_pipeline(meta_path, pkl)
            print("ok", meta_path.parent.name, pkl)
        except Exception as e:
            print(f"fail {meta_path}: {e}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
