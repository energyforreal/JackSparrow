#!/usr/bin/env python3
"""Write ``model_artifact_v43_patched.pkl`` with the runtime v43 threshold patch applied.

Matches idempotent logic in ``agent.models.jack_sparrow_v43_node._apply_v43_threshold_patch``.
Run from repo root with ``PYTHONPATH=.`` or via ``python -m`` after installing the package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(
        description="Patch v43 model artifact thresholds and save patched pickle.",
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=root / "agent" / "model_storage" / "JackSparrow_v43_models_BTCUSD",
        help="Directory containing metadata_v43.json and model artifact",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Input artifact (default: model_artifact_v43.pkl in bundle-dir)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: bundle-dir/model_artifact_v43_patched.pkl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print whether patch would apply; do not write pickle",
    )
    args = parser.parse_args()

    bundle = args.bundle_dir.expanduser().resolve()
    meta = bundle / "metadata_v43.json"
    if not meta.is_file():
        print(f"error: missing {meta}", file=sys.stderr)
        return 2

    src = (
        args.source.expanduser().resolve()
        if args.source
        else bundle / "model_artifact_v43.pkl"
    )
    if not src.is_file():
        print(f"error: source artifact not found: {src}", file=sys.stderr)
        return 2

    out = (
        args.out.expanduser().resolve()
        if args.out
        else bundle / "model_artifact_v43_patched.pkl"
    )

    from agent.models.jack_sparrow_v43_node import (  # noqa: WPS433
        _apply_v43_threshold_patch,
        _load,
    )

    artifact = _load(src)
    if not isinstance(artifact, dict):
        print("error: artifact must unpickle to a dict", file=sys.stderr)
        return 3

    patched = _apply_v43_threshold_patch(artifact)
    summary = {
        "source": str(src),
        "patched": bool(patched),
        "out": str(out) if not args.dry_run else None,
    }
    print(json.dumps(summary, indent=2))

    if args.dry_run:
        return 0

    try:
        import joblib  # type: ignore

        joblib.dump(artifact, out)
    except Exception as exc:
        print(f"error: failed to write {out}: {exc}", file=sys.stderr)
        return 4

    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
