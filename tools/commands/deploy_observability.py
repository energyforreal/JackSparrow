#!/usr/bin/env python3
"""Rebuild and restart agent container after observability patches."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy TLE observability patches to Docker")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--service", default="agent")
    args = parser.parse_args()

    compose = ["docker", "compose"]
    build = compose + ["build", args.service]
    print(">>>", " ".join(build))
    rc = subprocess.call(build, cwd=str(ROOT))
    if rc != 0:
        return rc
    if args.build_only:
        return 0
    up = compose + ["up", "-d", "--no-deps", args.service]
    print(">>>", " ".join(up))
    return subprocess.call(up, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
