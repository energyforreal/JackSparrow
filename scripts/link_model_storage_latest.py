#!/usr/bin/env python3
"""
Point agent/model_storage/latest at a trained model directory.

Usage:
  python scripts/link_model_storage_latest.py agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19

On Windows, creating symlinks may require Developer Mode or an elevated shell;
Docker/Linux deployments use normal symlinks.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Update agent/model_storage/latest symlink")
    parser.add_argument(
        "target",
        help="Directory to point at (relative to repo root or absolute)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    storage = root / "agent" / "model_storage"
    storage.mkdir(parents=True, exist_ok=True)

    target = Path(args.target)
    if not target.is_absolute():
        target = (root / target).resolve()
    else:
        target = target.resolve()

    if not target.exists():
        print(f"ERROR: target does not exist: {target}", file=sys.stderr)
        return 1
    if not target.is_dir():
        print(f"ERROR: target must be a directory: {target}", file=sys.stderr)
        return 1

    latest = storage / "latest"
    try:
        if latest.is_symlink():
            latest.unlink()
        elif latest.is_dir():
            try:
                latest.rmdir()
            except OSError:
                print(
                    f"ERROR: {latest} exists and is not an empty symlink; remove manually.",
                    file=sys.stderr,
                )
                return 1
        elif latest.exists():
            latest.unlink()

        latest.symlink_to(target, target_is_directory=True)
    except OSError as e:
        if os.name == "nt":
            print(
                f"ERROR: could not create symlink ({e}). On Windows enable Developer Mode "
                "or run as Administrator, or create the link manually.",
                file=sys.stderr,
            )
        else:
            print(f"ERROR: could not create symlink: {e}", file=sys.stderr)
        return 1

    print(f"OK: {latest} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
